import os
import sys
from pathlib import Path
from typing import Dict, List
from loguru import logger
from dotenv import load_dotenv
import openai

from instagram_client import InstagramClient
from chatgpt_client import ChatGPTClient

# Configure logging
logger.remove()
logger.add(sys.stderr, level="INFO")

def test_instagram_login():
    """Test Instagram login functionality"""
    load_dotenv()
    
    ig_username = os.getenv("IG_USERNAME")
    ig_password = os.getenv("IG_PASSWORD")
    
    if not all([ig_username, ig_password]):
        logger.error("Missing Instagram credentials in .env file")
        return
    
    try:
        logger.info(f"Attempting to log in to Instagram as {ig_username}")
        instagram = InstagramClient(ig_username, ig_password)
        logger.info(f"Login successful! User ID: {instagram.user_id}")
    except Exception as e:
        logger.error(f"Login failed: {e}")

def test_chatgpt_api():
    """Test ChatGPT API connectivity"""
    load_dotenv()
    
    api_key = os.getenv("OPENAI_API_KEY")
    
    if not api_key:
        logger.error("Missing OpenAI API key in .env file")
        return
    
    try:
        logger.info("Testing ChatGPT API...")
        
        # Create a simple test message
        messages = [{"role": "system", "content": "You are a helpful assistant."},
                  {"role": "user", "content": "Hello, how are you?"}]
        
        # Use the OpenAI client directly without the ChatGPTClient class
        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages,
            max_tokens=150
        )
        
        response_text = response.choices[0].message.content
        
        if response_text:
            logger.info(f"ChatGPT API test successful! Response: {response_text}")
        else:
            logger.error("Got empty response from ChatGPT API")
    except Exception as e:
        logger.error(f"ChatGPT API test failed: {e}")
        # Print more detailed error info
        import traceback
        logger.error(traceback.format_exc())

def list_unread_threads():
    """List all unread threads in the Instagram inbox"""
    load_dotenv()
    
    ig_username = os.getenv("IG_USERNAME")
    ig_password = os.getenv("IG_PASSWORD")
    
    if not all([ig_username, ig_password]):
        logger.error("Missing Instagram credentials in .env file")
        return
    
    try:
        instagram = InstagramClient(ig_username, ig_password)
        threads = instagram.get_unread_threads()
        
        if not threads:
            logger.info("No unread threads found")
            return
        
        logger.info(f"Found {len(threads)} unread threads:")
        
        for i, thread in enumerate(threads, 1):
            users = ", ".join([user.username for user in thread.users])
            logger.info(f"{i}. Thread ID: {thread.id} - Users: {users} - Unread count: {thread.unread_count}")
    except Exception as e:
        logger.error(f"Error listing unread threads: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python utils.py [test_login|test_chatgpt|list_threads]")
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == "test_login":
        test_instagram_login()
    elif command == "test_chatgpt":
        test_chatgpt_api()
    elif command == "list_threads":
        list_unread_threads()
    else:
        print(f"Unknown command: {command}")
        print("Available commands: test_login, test_chatgpt, list_threads")
        sys.exit(1) 