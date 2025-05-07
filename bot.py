import os
import time
import sys
import random
import traceback
from pathlib import Path
from typing import Dict, List, Optional
from loguru import logger
from dotenv import load_dotenv

from instagram_client import InstagramClient
from chatgpt_client import ChatGPTClient
from db_helper import MongoDBHelper
from dashboard_db import DashboardDBHelper

# Load environment variables first to configure logging
load_dotenv()

# Set up debug mode from environment
debug_mode = bool(int(os.getenv("DEBUG_MODE", "0")))
console_log_level = "DEBUG" if debug_mode else "INFO"

# Parse preserving conversation context setting
preserve_context = bool(int(os.getenv("PRESERVE_CONTEXT", "1")))
context_message_limit = int(os.getenv("CONTEXT_MESSAGE_LIMIT", "10"))

# Configure logging
logger.remove()
logger.add(sys.stderr, level=console_log_level)
logger.add("bot.log", rotation="10 MB", level="DEBUG")  # Save all debug info to the log file
logger.add("bot_chat.log", rotation="10 MB", level="DEBUG", 
          filter=lambda record: "[CHATGPT" in record["message"])  # Separate log file for ChatGPT interactions

if debug_mode:
    logger.info("Debug mode enabled - verbose logging will be displayed")

class InstagramDMBot:
    def __init__(self):
        # Environment variables are already loaded
        
        # Get configuration
        self.ig_username = os.getenv("IG_USERNAME", "")
        self.ig_password = os.getenv("IG_PASSWORD", "")
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")
        self.mongodb_uri = os.getenv("MONGODB_URI", "")
        self.dashboard_db_uri = os.getenv("DASHBOARD_DB_URI", "")
        self.dashboard_db_name = os.getenv("DASHBOARD_DB_NAME", "instagram_dashboard")
        self.debug_mode = debug_mode
        self.preserve_context = preserve_context
        self.context_message_limit = context_message_limit
        
        # Parse check interval safely
        check_interval_str = os.getenv("CHECK_INTERVAL", "60")
        try:
            self.check_interval = int(check_interval_str.strip())
        except ValueError:
            logger.warning(f"Invalid CHECK_INTERVAL value '{check_interval_str}', using default of 60 seconds")
            self.check_interval = 60
            
        self.response_prefix = os.getenv("RESPONSE_PREFIX", "")
        self.combine_messages = bool(int(os.getenv("COMBINE_MESSAGES", "1")))
        self.combine_limit = int(os.getenv("COMBINE_LIMIT", "5"))
        
        # Backoff timers for API calls
        self.pending_backoff_time = self.check_interval  # Start with the default check interval
        self.inbox_backoff_time = self.check_interval  # Start with the default check interval
        self.max_backoff_time = self.check_interval * 8  # Maximum backoff time (8x the default)
        self.backoff_factor = 1.5  # Each unsuccessful check multiplies the wait time by this factor
        
        # Track whether we found messages in previous checks
        self.found_pending_messages = False
        self.found_inbox_messages = False
        
        # Validate configuration
        if not all([self.ig_username, self.ig_password, self.openai_api_key]):
            logger.error("Missing required environment variables. Please check your .env file")
            sys.exit(1)
        
        # Log configuration in debug mode
        if self.debug_mode:
            logger.debug(f"Configuration loaded: ")
            logger.debug(f"Username: {self.ig_username}")
            logger.debug(f"Check interval: {self.check_interval}")
            logger.debug(f"Response prefix: {self.response_prefix}")
            logger.debug(f"Combine messages: {self.combine_messages}")
            logger.debug(f"Combine limit: {self.combine_limit}")
            logger.debug(f"MongoDB URI: {'Set' if self.mongodb_uri else 'Not set'}")
            logger.debug(f"Dashboard DB URI: {'Set' if self.dashboard_db_uri else 'Not set'}")
            logger.debug(f"Max backoff time: {self.max_backoff_time} seconds")
            logger.debug(f"Backoff factor: {self.backoff_factor}x")
            logger.debug(f"Preserve context: {self.preserve_context}")
            logger.debug(f"Context message limit: {self.context_message_limit}")
        
        # Initialize clients
        self.instagram = InstagramClient(self.ig_username, self.ig_password)
        self.chatgpt = ChatGPTClient(self.openai_api_key)
        self.db = MongoDBHelper(self.mongodb_uri if self.mongodb_uri else None)
        self.dashboard_db = DashboardDBHelper(self.dashboard_db_uri, self.dashboard_db_name)
        
        # Track processed messages to avoid duplicate responses
        self.processed_message_ids = set()
        
    def sleep_with_jitter(self, base_seconds: float = 3.0, jitter_seconds: float = 2.0) -> None:
        """Sleep for a random amount of time to avoid detection"""
        sleep_time = base_seconds + random.uniform(0, jitter_seconds)
        logger.debug(f"Sleeping for {sleep_time:.2f} seconds")
        time.sleep(sleep_time)
        
    def identify_user_messages(self, messages: List) -> List:
        """
        Identify user messages without relying on user_id matching
        Compare with last known bot message to determine which messages are from the user
        """
        if not messages:
            return []
            
        thread_id = None
        if hasattr(messages[0], 'thread_id'):
            thread_id = messages[0].thread_id
        
        # Get the last bot message from the database
        last_bot_message = self.db.get_last_bot_message(thread_id) if thread_id else None
        
        user_messages = []
        found_last_bot_message = last_bot_message is None  # If None, we don't have a last bot message to find
        
        # Iterate through messages from newest to oldest
        for msg in messages:
            if not hasattr(msg, 'text') or not msg.text:
                continue
                
            # If we've found the last bot message, everything newer is from the user
            if found_last_bot_message:
                user_messages.append(msg)
            elif last_bot_message and msg.text == last_bot_message:
                # We found our last bot message, so everything after this is from the user
                found_last_bot_message = True
        
        return user_messages
    
    def get_username_from_thread(self, thread) -> str:
        """Extract username from thread object"""
        username = "unknown_user"
        try:
            # Try different attributes where username might be found
            if hasattr(thread, 'thread_title'):
                username = thread.thread_title
            elif hasattr(thread, 'users') and thread.users and len(thread.users) > 0:
                if hasattr(thread.users[0], 'username'):
                    username = thread.users[0].username
                elif hasattr(thread.users[0], 'full_name'):
                    username = thread.users[0].full_name
            elif hasattr(thread, 'inviter') and hasattr(thread.inviter, 'username'):
                username = thread.inviter.username
        except Exception as e:
            logger.warning(f"Could not extract username from thread: {e}")
        
        return username
        
    def process_thread(self, thread_id: str, thread=None, is_pending: bool = False) -> None:
        """Process a single message thread"""
        try:
            logger.info(f"[THREAD] Processing thread {thread_id} (pending: {is_pending})")
            
            # Extract username from thread if available
            username = "unknown_user"
            if thread:
                username = self.get_username_from_thread(thread)
            
            # Update thread status in dashboard
            if is_pending:
                self.dashboard_db.update_thread_status(thread_id, username, "pending")
            
            # If it's a pending thread, try to approve it first
            if is_pending:
                logger.info(f"Approving pending thread {thread_id}")
                approval_success = self.instagram.approve_pending_thread(thread_id)
                if not approval_success:
                    logger.warning(f"Could not explicitly approve thread {thread_id}, but will try to process it anyway")
                    # Continue with processing even if approval fails
                else:
                    # Update status in dashboard after approval
                    self.dashboard_db.update_thread_status(thread_id, username, "active")
                
                # Add a delay after approval attempt
                self.sleep_with_jitter(2.0, 1.0)
            
            # Get thread messages (we'll get more messages if context preservation is enabled)
            message_limit = max(10, self.context_message_limit) if self.preserve_context else 10
            messages = self.instagram.get_thread_messages(thread_id, limit=message_limit)
            
            if not messages:
                logger.warning(f"No messages found in thread {thread_id}")
                return
            
            logger.info(f"[THREAD] Retrieved {len(messages)} messages from thread {thread_id}")
            
            # Try to get username from messages if we don't have it
            if username == "unknown_user" and messages:
                # Look for non-bot messages to get username
                for msg in messages:
                    if hasattr(msg, 'user_id') and hasattr(msg, 'is_sent_by_viewer') and not msg.is_sent_by_viewer:
                        if hasattr(msg, 'username'):
                            username = msg.username
                            break
            
            # Add a delay after fetching messages
            self.sleep_with_jitter(1.0, 1.0)
            
            # Check if we've already processed the latest message
            latest_message = messages[0]  # First message is the most recent
            
            if not hasattr(latest_message, 'id'):
                logger.warning(f"Latest message has no ID, skipping thread {thread_id}")
                return
                
            if latest_message.id in self.processed_message_ids:
                logger.debug(f"Already processed message {latest_message.id}")
                return
            
            # Get only messages that came after the last bot response
            new_messages = self.db.get_messages_after_last_bot_response(thread_id, messages)
            
            logger.info(f"[THREAD] Found {len(new_messages)} new messages after last bot response in thread {thread_id}")
            
            if not new_messages:
                logger.debug(f"No new messages found after last bot response in thread {thread_id}")
                if hasattr(latest_message, 'id'):
                    self.processed_message_ids.add(latest_message.id)
                return
            
            # Identify user messages using our custom method
            user_messages = self.identify_user_messages(new_messages)
            
            logger.info(f"[THREAD] Identified {len(user_messages)} user messages from new messages in thread {thread_id}")
            
            if not user_messages:
                logger.debug(f"No new user messages found in thread {thread_id}")
                if hasattr(latest_message, 'id'):
                    self.processed_message_ids.add(latest_message.id)
                return
            
            # Store the user messages in both databases
            stored_message_count = 0
            
            # Since user_messages is in reverse chronological order (newest first),
            # we need to reverse it when storing to the dashboard to maintain chronological order
            chronological_user_messages = list(reversed(user_messages))
            
            # Log the order of messages being stored
            if len(chronological_user_messages) > 0 and self.debug_mode:
                first_msg = chronological_user_messages[0].text if hasattr(chronological_user_messages[0], 'text') else "No text"
                last_msg = chronological_user_messages[-1].text if hasattr(chronological_user_messages[-1], 'text') else "No text"
                logger.debug(f"[DASHBOARD] Storing messages in chronological order, first: '{first_msg[:30]}...', last: '{last_msg[:30]}...'")
            
            for msg in chronological_user_messages:
                if hasattr(msg, 'id') and hasattr(msg, 'text'):
                    # Store in conversation database
                    success = self.db.save_message(thread_id, msg.id, msg.text, is_from_bot=False)
                    
                    # Also store in dashboard database in chronological order
                    dash_success = self.dashboard_db.store_message(
                        thread_id, 
                        username, 
                        msg.text, 
                        is_from_bot=False, 
                        message_id=msg.id
                    )
                    
                    if success:
                        stored_message_count += 1
            
            logger.info(f"[THREAD] Stored {stored_message_count} user messages in database for thread {thread_id}")
            
            # Check if this is the first interaction with this user
            is_first_interaction = self.db.is_first_interaction(thread_id)
            logger.info(f"[THREAD] Is first interaction: {is_first_interaction}")
            
            # Get combined user message
            combined_text = ""
            if self.combine_messages:
                # Extract and combine text from user messages
                combined_text = self.chatgpt.extract_text_from_messages(user_messages[:self.combine_limit])
                logger.info(f"[THREAD] Combined {min(len(user_messages), self.combine_limit)} messages. Text length: {len(combined_text)}")
            else:
                # Just use the latest message
                if hasattr(latest_message, 'text') and latest_message.text:
                    combined_text = latest_message.text
                    logger.info(f"[THREAD] Using only the latest message. Text length: {len(combined_text)}")
            
            if not combined_text:
                logger.warning(f"No valid text could be extracted from messages in thread {thread_id}")
                return
            
            # Log a preview of the combined text (truncated for readability)
            preview_length = min(50, len(combined_text))
            logger.info(f"[THREAD] Message preview: {combined_text[:preview_length]}{'...' if len(combined_text) > preview_length else ''}")
            
            # Process conversation history for context if enabled
            conversation_history = None
            if self.preserve_context:
                # Get conversation history (limited by context_message_limit)
                # We will only use the first X messages from the full thread
                history_messages = messages[:self.context_message_limit]
                
                # Format history messages for ChatGPT
                conversation_history = self.chatgpt.format_conversation_history(
                    history_messages, 
                    self.ig_username
                )
                
                logger.info(f"[THREAD] Using {len(conversation_history)} messages for conversation history")
                
                # Detailed logging in debug mode
                if self.debug_mode and conversation_history:
                    logger.debug("[THREAD] Conversation history preview:")
                    for i, msg in enumerate(conversation_history[:5]):  # Show first 5 messages
                        logger.debug(f"  {i+1}. {msg['role']}: {msg['content'][:30]}...")
                    if len(conversation_history) > 5:
                        logger.debug(f"  ... and {len(conversation_history) - 5} more messages")
                
            # Add a delay before calling ChatGPT
            self.sleep_with_jitter(1.0, 1.0)
                
            # Get response from ChatGPT
            logger.info(f"[THREAD] Sending message to ChatGPT for thread {thread_id}")
            response = self.chatgpt.get_response(
                combined_text, 
                is_first_interaction=is_first_interaction,
                conversation_history=conversation_history
            )
            
            # Record API call in dashboard
            self.dashboard_db.record_api_call("chatgpt", response is not None)
            
            if not response:
                logger.error(f"Failed to get response from ChatGPT for thread {thread_id}")
                return
                
            # Add prefix if configured
            if self.response_prefix:
                response = f"{self.response_prefix}{response}"
                logger.debug(f"[THREAD] Added response prefix. New length: {len(response)}")
                
            # Add a delay before sending the response
            self.sleep_with_jitter(2.0, 2.0)
                
            # Send the response
            logger.info(f"[THREAD] Sending response to Instagram for thread {thread_id}")
            success = self.instagram.send_message(thread_id, response)
            
            # Record Instagram API call in dashboard
            self.dashboard_db.record_api_call("instagram", success)
            
            if success:
                # Save the bot's message to both databases
                db_success = self.db.save_message(thread_id, f"bot_{int(time.time())}", response, is_from_bot=True)
                
                # Save to dashboard database
                dash_success = self.dashboard_db.store_message(
                    thread_id, 
                    username, 
                    response, 
                    is_from_bot=True
                )
                
                logger.info(f"[THREAD] Saved bot response to database: {db_success}")
                
                # Mark the message as processed
                self.processed_message_ids.add(latest_message.id)
                
                # Add a delay before marking the thread as seen
                self.sleep_with_jitter(2.0, 1.0)
                
                # Mark the thread as seen
                self.instagram.mark_thread_seen(thread_id)
                logger.info(f"Successfully responded to thread {thread_id}")
            else:
                logger.error(f"Failed to send response to thread {thread_id}")
        except Exception as e:
            logger.error(f"Error processing thread {thread_id}: {e}")
            logger.error(traceback.format_exc())
    
    def process_pending_threads(self) -> bool:
        """
        Process all pending message requests
        
        Returns:
            bool: True if any pending messages were found, False otherwise
        """
        try:
            # Try multiple methods to get pending threads
            pending_threads = []
            pending_thread_ids = []
            any_pending_found = False
            
            # First try to get pending thread objects
            try:
                pending_threads = self.instagram.get_pending_threads()
                if pending_threads:
                    logger.info(f"Found {len(pending_threads)} pending message requests via get_pending_threads")
                    any_pending_found = True
            except Exception as e:
                logger.warning(f"Error getting pending threads via get_pending_threads: {e}")
                
            # Add a delay between API calls
            self.sleep_with_jitter(3.0, 2.0)
                
            # If that fails or returns no results, try to get just the IDs
            if not pending_threads:
                try:
                    pending_thread_ids = self.instagram.get_pending_thread_ids()
                    if pending_thread_ids:
                        logger.info(f"Found {len(pending_thread_ids)} pending message requests via get_pending_thread_ids")
                        any_pending_found = True
                except Exception as e:
                    logger.warning(f"Error getting pending thread IDs via get_pending_thread_ids: {e}")
            
            # Record API call in dashboard
            self.dashboard_db.record_api_call("instagram_pending", any_pending_found)
            
            # Process thread objects
            if pending_threads:
                for thread in pending_threads:
                    if hasattr(thread, 'id'):
                        self.process_thread(thread.id, thread=thread, is_pending=True)
                    else:
                        logger.warning("Found pending thread without an ID, skipping")
                    # Add a significant delay between processing threads
                    self.sleep_with_jitter(5.0, 3.0)
            # Process thread IDs
            elif pending_thread_ids:
                for thread_id in pending_thread_ids:
                    self.process_thread(thread_id, is_pending=True)
                    # Add a significant delay between processing threads
                    self.sleep_with_jitter(5.0, 3.0)
            else:
                logger.info("No pending message requests found")
                
            return any_pending_found
                
        except Exception as e:
            logger.error(f"Error processing pending threads: {e}")
            logger.error(traceback.format_exc())
            return False
            
    def process_inbox_threads(self) -> bool:
        """
        Process unread threads in the inbox
        
        Returns:
            bool: True if any unread messages were found, False otherwise
        """
        try:
            # Check regular unread threads
            unread_threads = self.instagram.get_unread_threads()
            
            # Record API call in dashboard
            self.dashboard_db.record_api_call("instagram_inbox", unread_threads is not None and len(unread_threads) > 0)
            
            if unread_threads:
                logger.info(f"Found {len(unread_threads)} unread threads")
                
                # Process each thread
                for thread in unread_threads:
                    if hasattr(thread, 'id'):
                        self.process_thread(thread.id, thread=thread)
                    else:
                        logger.warning("Found thread without an ID, skipping")
                    # Add a significant delay between processing threads
                    self.sleep_with_jitter(5.0, 3.0)
                    
                return True
            else:
                logger.info("No unread threads found")
                return False
                
        except Exception as e:
            logger.error(f"Error processing inbox threads: {e}")
            logger.error(traceback.format_exc())
            return False
            
    def adjust_backoff_times(self, found_pending: bool, found_inbox: bool) -> None:
        """
        Adjust backoff times based on whether messages were found
        
        Args:
            found_pending: Whether pending messages were found
            found_inbox: Whether inbox messages were found
        """
        # Update backoff times for pending requests
        if found_pending:
            # Reset backoff time if messages were found
            self.pending_backoff_time = self.check_interval
            logger.debug(f"Pending messages found - reset pending backoff time to {self.pending_backoff_time} seconds")
        else:
            # Increase backoff time if no messages were found
            self.pending_backoff_time = min(self.pending_backoff_time * self.backoff_factor, self.max_backoff_time)
            logger.debug(f"No pending messages found - increased pending backoff time to {self.pending_backoff_time:.1f} seconds")
            
        # Update backoff times for inbox
        if found_inbox:
            # Reset backoff time if messages were found
            self.inbox_backoff_time = self.check_interval
            logger.debug(f"Inbox messages found - reset inbox backoff time to {self.inbox_backoff_time} seconds")
        else:
            # Increase backoff time if no messages were found
            self.inbox_backoff_time = min(self.inbox_backoff_time * self.backoff_factor, self.max_backoff_time)
            logger.debug(f"No inbox messages found - increased inbox backoff time to {self.inbox_backoff_time:.1f} seconds")
            
    def run(self) -> None:
        """Main loop to continuously check for and respond to messages using exponential backoff"""
        logger.info(f"Instagram DM Bot started for user {self.ig_username}")
        
        try:
            # Track the last check times
            last_pending_check = 0
            last_inbox_check = 0
            
            while True:
                try:
                    current_time = time.time()
                    
                    # Check if it's time to check pending requests
                    if current_time - last_pending_check >= self.pending_backoff_time:
                        logger.info(f"Checking pending messages (backoff: {self.pending_backoff_time:.1f}s)")
                        found_pending = self.process_pending_threads()
                        last_pending_check = current_time
                        
                        # Add a delay between checking pending and inbox
                        self.sleep_with_jitter(5.0, 3.0)
                        current_time = time.time()  # Update current time after delay
                    else:
                        # Log time remaining until next pending check
                        time_to_pending = last_pending_check + self.pending_backoff_time - current_time
                        logger.debug(f"Next pending check in {time_to_pending:.1f} seconds")
                        found_pending = False  # No check was performed
                    
                    # Check if it's time to check inbox
                    if current_time - last_inbox_check >= self.inbox_backoff_time:
                        logger.info(f"Checking inbox messages (backoff: {self.inbox_backoff_time:.1f}s)")
                        found_inbox = self.process_inbox_threads()
                        last_inbox_check = current_time
                    else:
                        # Log time remaining until next inbox check
                        time_to_inbox = last_inbox_check + self.inbox_backoff_time - current_time
                        logger.debug(f"Next inbox check in {time_to_inbox:.1f} seconds")
                        found_inbox = False  # No check was performed
                    
                    # Adjust backoff times based on whether messages were found
                    if found_pending or found_inbox:
                        self.adjust_backoff_times(found_pending, found_inbox)
                        
                    # Cap the processed message IDs to prevent unlimited growth
                    if len(self.processed_message_ids) > 1000:
                        logger.info("Pruning processed message IDs")
                        # Keep only the 500 most recent IDs
                        self.processed_message_ids = set(list(self.processed_message_ids)[-500:])
                except Exception as e:
                    logger.error(f"Error in main loop: {e}")
                    logger.error(traceback.format_exc())
                
                # Calculate the next sleep duration based on the minimum time to next check
                next_pending_check = last_pending_check + self.pending_backoff_time
                next_inbox_check = last_inbox_check + self.inbox_backoff_time
                time_to_next_check = min(next_pending_check, next_inbox_check) - time.time()
                
                # Add some jitter to avoid predictable patterns, but ensure minimum interval
                jitter = random.uniform(-2, 2)  # +/- 2 seconds
                sleep_duration = max(10, time_to_next_check + jitter)  # At least 10 seconds
                
                logger.info(f"Sleeping for {sleep_duration:.1f} seconds until next check")
                time.sleep(sleep_duration)
                
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            logger.error(traceback.format_exc())

if __name__ == "__main__":
    bot = InstagramDMBot()
    bot.run() 