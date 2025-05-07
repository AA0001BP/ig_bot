import os
import time
from datetime import datetime
from typing import List, Dict, Optional, Any
from loguru import logger
import pymongo
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

class MongoDBHelper:
    def __init__(self, connection_string: Optional[str] = None, db_name: str = "instagram_bot"):
        """Initialize MongoDB connection"""
        try:
            # Use provided connection string or create a local connection
            if connection_string:
                self.client = MongoClient(connection_string)
            else:
                # Use localhost by default
                self.client = MongoClient("mongodb://localhost:27017/")
                
            self.db: Database = self.client[db_name]
            self.messages: Collection = self.db["messages"]
            self.threads: Collection = self.db["threads"]
            self.bot_messages: Collection = self.db["bot_messages"]  # New collection for bot messages only
            
            # Create indexes for faster lookups
            self.messages.create_index([("thread_id", pymongo.ASCENDING), ("timestamp", pymongo.DESCENDING)])
            self.threads.create_index([("thread_id", pymongo.ASCENDING)], unique=True)
            self.bot_messages.create_index([("thread_id", pymongo.ASCENDING)], unique=True)
            
            logger.info(f"Connected to MongoDB: {db_name}")
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            # Create in-memory fallback
            self.client = None
            self.in_memory_messages = {}
            self.in_memory_threads = {}
            self.in_memory_bot_messages = {}  # In-memory fallback for bot messages
            logger.warning("Using in-memory storage as fallback")
    
    def is_connected(self) -> bool:
        """Check if MongoDB is connected"""
        return self.client is not None
    
    def save_message(self, thread_id: str, message_id: str, text: str, is_from_bot: bool) -> bool:
        """
        Save a message to the database
        For bot messages, we only keep the latest one per thread
        """
        try:
            timestamp = datetime.now()
            
            # Only store user messages in the messages collection
            if not is_from_bot:
                message_data = {
                    "thread_id": thread_id,
                    "message_id": message_id,
                    "text": text,
                    "is_from_bot": False,
                    "timestamp": timestamp
                }
                
                if self.is_connected():
                    self.messages.insert_one(message_data)
                else:
                    # In-memory fallback
                    if thread_id not in self.in_memory_messages:
                        self.in_memory_messages[thread_id] = []
                    self.in_memory_messages[thread_id].append(message_data)
            
            # For bot messages, overwrite the previous bot message
            if is_from_bot:
                bot_message_data = {
                    "thread_id": thread_id,
                    "message_id": message_id,
                    "text": text,
                    "timestamp": timestamp
                }
                
                if self.is_connected():
                    # Replace the existing bot message for this thread or insert a new one
                    self.bot_messages.replace_one(
                        {"thread_id": thread_id},
                        bot_message_data,
                        upsert=True
                    )
                else:
                    # In-memory fallback
                    self.in_memory_bot_messages[thread_id] = bot_message_data
            
            # Update the thread with last message info
            if self.is_connected():
                self.threads.update_one(
                    {"thread_id": thread_id},
                    {"$set": {
                        "last_message": text,
                        "last_message_timestamp": timestamp,
                        "last_message_from_bot": is_from_bot
                    }},
                    upsert=True
                )
            else:
                self.in_memory_threads[thread_id] = {
                    "thread_id": thread_id,
                    "last_message": text,
                    "last_message_timestamp": timestamp,
                    "last_message_from_bot": is_from_bot
                }
                
            logger.debug(f"Saved message to thread {thread_id}: {'Bot' if is_from_bot else 'User'} - {text[:30]}...")
            return True
        except Exception as e:
            logger.error(f"Error saving message to database: {e}")
            return False
    
    def get_last_bot_message(self, thread_id: str) -> Optional[str]:
        """Get the last message sent by the bot in a thread"""
        try:
            if self.is_connected():
                bot_message = self.bot_messages.find_one({"thread_id": thread_id})
                if bot_message:
                    return bot_message.get("text")
            else:
                # In-memory fallback
                if thread_id in self.in_memory_bot_messages:
                    return self.in_memory_bot_messages[thread_id].get("text")
            
            return None
        except Exception as e:
            logger.error(f"Error getting last bot message: {e}")
            return None
    
    def get_last_bot_message_timestamp(self, thread_id: str) -> Optional[datetime]:
        """Get the timestamp of the last bot message in a thread"""
        try:
            if self.is_connected():
                bot_message = self.bot_messages.find_one({"thread_id": thread_id})
                if bot_message:
                    return bot_message.get("timestamp")
            else:
                # In-memory fallback
                if thread_id in self.in_memory_bot_messages:
                    return self.in_memory_bot_messages[thread_id].get("timestamp")
            
            return None
        except Exception as e:
            logger.error(f"Error getting last bot message timestamp: {e}")
            return None
    
    def get_messages_after_last_bot_response(self, thread_id: str, messages: List[Any]) -> List[Any]:
        """
        Filter messages to only include those that came after the last bot response
        
        Args:
            thread_id: The ID of the thread
            messages: List of Instagram DirectMessage objects
            
        Returns:
            List of messages that came after the last bot response
        """
        try:
            # Get the timestamp of the last bot message
            last_bot_timestamp = self.get_last_bot_message_timestamp(thread_id)
            
            # If no previous bot message, return all messages
            if not last_bot_timestamp:
                logger.debug(f"No previous bot message found for thread {thread_id}, returning all messages")
                return messages
            
            # Filter messages that came after the last bot message
            new_messages = []
            for msg in messages:
                # Check if the message has a timestamp
                if hasattr(msg, 'timestamp') and msg.timestamp:
                    # Convert message timestamp to datetime if needed
                    msg_timestamp = msg.timestamp
                    if not isinstance(msg_timestamp, datetime):
                        # Handle potential string formats if necessary
                        if isinstance(msg_timestamp, str):
                            try:
                                msg_timestamp = datetime.fromisoformat(msg_timestamp)
                            except ValueError:
                                # If parsing fails, try compare by string
                                if str(msg_timestamp) > str(last_bot_timestamp):
                                    new_messages.append(msg)
                                continue
                    
                    # Compare timestamps
                    if msg_timestamp > last_bot_timestamp:
                        new_messages.append(msg)
                else:
                    # If no timestamp, include the message to be safe
                    new_messages.append(msg)
            
            logger.debug(f"Filtered {len(messages)} messages to {len(new_messages)} new messages for thread {thread_id}")
            return new_messages
        except Exception as e:
            logger.error(f"Error filtering messages after last bot response: {e}")
            return messages  # Return all messages in case of error
    
    def get_recent_user_messages(self, thread_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Get recent messages from user in a thread"""
        try:
            user_messages = []
            
            if self.is_connected():
                cursor = self.messages.find(
                    {"thread_id": thread_id, "is_from_bot": False},
                    sort=[("timestamp", pymongo.DESCENDING)],
                    limit=limit
                )
                
                user_messages = list(cursor)
                # Reverse to get chronological order
                user_messages.reverse()
            else:
                # In-memory fallback
                if thread_id in self.in_memory_messages:
                    messages = [msg for msg in self.in_memory_messages[thread_id] 
                               if not msg.get("is_from_bot")]
                    user_messages = sorted(messages, key=lambda x: x.get("timestamp", 0))[-limit:]
            
            return user_messages
        except Exception as e:
            logger.error(f"Error getting recent user messages: {e}")
            return []
    
    def get_combined_user_messages(self, thread_id: str, limit: int = 5) -> Optional[str]:
        """Get combined text of recent user messages"""
        try:
            user_messages = self.get_recent_user_messages(thread_id, limit)
            
            if not user_messages:
                return None
                
            combined_text = "\n".join([msg.get("text", "") for msg in user_messages])
            return combined_text
        except Exception as e:
            logger.error(f"Error getting combined user messages: {e}")
            return None
    
    def is_first_interaction(self, thread_id: str) -> bool:
        """Check if this is the first interaction with this thread"""
        try:
            if self.is_connected():
                # Check if there's a bot message for this thread
                bot_count = self.bot_messages.count_documents({"thread_id": thread_id})
                return bot_count == 0
            else:
                # In-memory fallback
                return thread_id not in self.in_memory_bot_messages
        except Exception as e:
            logger.error(f"Error checking first interaction: {e}")
            return True  # Assume it's the first interaction if error occurs 