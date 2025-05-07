import os
from typing import List, Dict, Optional, Any
from loguru import logger
import openai
import json
from pathlib import Path

class ChatGPTClient:
    def __init__(self, api_key: str, model: str = "gpt-4.1-nano-2025-04-14"):
        self.api_key = api_key
        self.model = model
        # Initialize the OpenAI client with just the API key
        self.client = openai.OpenAI(api_key=api_key)
        
        # Load system prompt from file
        self.system_prompt = self.load_system_prompt()
        logger.debug(f"Loaded system prompt with {len(self.system_prompt)} characters")
        
    def load_system_prompt(self) -> str:
        """Load the system prompt from the text file"""
        try:
            # Look for the file in the current directory
            prompt_file = Path("system_prompt.txt")
            
            # If not found, also check in the script's directory
            if not prompt_file.exists():
                script_dir = Path(__file__).parent
                prompt_file = script_dir / "system_prompt.txt"
            
            if prompt_file.exists():
                with open(prompt_file, "r", encoding="utf-8") as file:
                    prompt = file.read().strip()
                    logger.info(f"Successfully loaded system prompt from {prompt_file}")
                    return prompt
            else:
                # Fall back to a default prompt if the file doesn't exist
                logger.warning(f"Could not find system_prompt.txt, using default prompt")
                return """
                You are an AI assistant managing Instagram direct messages.
                Be helpful, friendly, and concise in your responses.
                For new users who have just sent a message request, be welcoming and introduce yourself briefly.
                Respond only to the most recent message or group of messages.
                Avoid mentioning that you're an AI unless directly asked.
                Keep responses brief and conversational, suitable for Instagram messaging.
                If asked about services, products, or business inquiries, respond professionally and ask for details.
                """
        except Exception as e:
            logger.error(f"Error loading system prompt: {e}")
            # Fall back to a default prompt in case of error
            return "You are a helpful assistant managing Instagram direct messages."
        
    def get_response(self, user_message: str, is_first_interaction: bool = False, 
                     max_tokens: int = 15000, conversation_history: Optional[List[Dict[str, str]]] = None) -> Optional[str]:
        """
        Get a response from ChatGPT based on the user message and conversation history
        
        Args:
            user_message: The combined message from the user
            is_first_interaction: Whether this is the first time talking to this user
            max_tokens: Maximum tokens in the response
            conversation_history: Optional list of previous messages in the conversation
            
        Returns:
            Response text or None if there was an error
        """
        try:
            # Customize system prompt for first-time interactions
            system_prompt = self.system_prompt
            if is_first_interaction:
                system_prompt += "\nThis is your first interaction with this user. Be welcoming and friendly."
            
            # Initialize messages with system prompt
            messages = [
                {"role": "system", "content": system_prompt}
            ]
            
            # Add conversation history if provided
            if conversation_history and len(conversation_history) > 0:
                logger.info(f"Including {len(conversation_history)} previous messages in conversation history")
                messages.extend(conversation_history)
            
            # Add the current user message
            messages.append({"role": "user", "content": user_message})
            
            # Log the messages being sent to ChatGPT
            logger.info(f"[CHATGPT INPUT] System prompt: {system_prompt[:100]}...")
            logger.info(f"[CHATGPT INPUT] User message: {user_message}")
            if conversation_history:
                logger.info(f"[CHATGPT INPUT] Conversation history length: {len(conversation_history)} messages")
            
            # For debugging, also log the full JSON payload
            debug_payload = {
                "model": self.model,
                "messages": messages,
                "max_tokens": max_tokens
            }
            logger.debug(f"[CHATGPT PAYLOAD] {json.dumps(debug_payload, indent=2)}")
            
            # Call the OpenAI API
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.7
            )
            
            # Extract and return the response text
            response_text = response.choices[0].message.content
            
            # Log the response from ChatGPT
            logger.info(f"[CHATGPT RESPONSE] {response_text}")
            
            return response_text.strip()
            
        except Exception as e:
            logger.error(f"Error getting ChatGPT response: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    def extract_text_from_messages(self, messages: List) -> str:
        """
        Extract text from Instagram messages regardless of sender
        
        Args:
            messages: List of Instagram DirectMessage objects
            
        Returns:
            Combined message text in chronological order (oldest to newest)
        """
        combined_text = []
        
        # Messages come in reverse chronological order (newest first)
        # We need to reverse them to get chronological order (oldest first)
        for msg in reversed(messages):
            if hasattr(msg, 'text') and msg.text:
                combined_text.append(msg.text)
                
        result = "\n".join(combined_text) if combined_text else ""
        logger.debug(f"[EXTRACTED MESSAGES] Combined {len(combined_text)} messages in chronological order, total length: {len(result)}")
        
        # Log the first message and the last message to verify order
        if combined_text:
            logger.debug(f"[EXTRACTED MESSAGES] First (oldest) message: {combined_text[0][:50]}...")
            logger.debug(f"[EXTRACTED MESSAGES] Last (newest) message: {combined_text[-1][:50]}...")
        
        return result

    def format_conversation_history(self, previous_messages: List, bot_username: str) -> List[Dict[str, str]]:
        """
        Format previous messages into a format suitable for the ChatGPT API
        
        Args:
            previous_messages: List of messages from the thread
            bot_username: Username of the bot, to identify bot messages
            
        Returns:
            List of messages in the format expected by ChatGPT API
        """
        formatted_messages = []
        
        # Need to go through messages in chronological order (oldest to newest)
        for msg in reversed(previous_messages):  # Messages are in reverse chronological order
            if not hasattr(msg, 'text') or not msg.text:
                continue
                
            # Skip messages that just contain the response prefix (like "[Bot] ")
            response_prefix = os.getenv("RESPONSE_PREFIX", "")
            if response_prefix and msg.text.strip() == response_prefix.strip():
                continue
                
            # Determine if the message is from the bot or the user
            role = "assistant" if hasattr(msg, 'is_sent_by_viewer') and msg.is_sent_by_viewer else "user"
            
            # Remove bot prefix from assistant messages if present
            content = msg.text
            if role == "assistant" and response_prefix and content.startswith(response_prefix):
                content = content[len(response_prefix):].strip()
                
            formatted_messages.append({
                "role": role,
                "content": content
            })
            
        # Log the formatted conversation history
        if formatted_messages:
            logger.debug(f"Formatted {len(formatted_messages)} messages for conversation history")
            for i, msg in enumerate(formatted_messages):
                logger.debug(f"[HISTORY {i+1}] {msg['role']}: {msg['content'][:30]}...")
                
        return formatted_messages

    def format_instagram_conversation(self, messages: List, username: str) -> List[Dict[str, str]]:
        """
        Format Instagram messages into a format suitable for ChatGPT
        
        Args:
            messages: List of Instagram DirectMessage objects
            username: Your Instagram username to differentiate messages
            
        Returns:
            List of message dictionaries with 'role' and 'content'
        """
        formatted_messages = []
        
        for msg in reversed(messages):  # Process from oldest to newest
            if not hasattr(msg, 'text') or not msg.text:  # Skip non-text messages
                continue
                
            # Determine if message is from the user or the bot
            if msg.user_id != username:  # Message from the other user
                formatted_messages.append({
                    "role": "user",
                    "content": msg.text
                })
            else:  # Message from the bot/account owner
                formatted_messages.append({
                    "role": "assistant", 
                    "content": msg.text
                })
        
        return formatted_messages 