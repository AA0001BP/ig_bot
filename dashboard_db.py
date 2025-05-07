import os
import time
from datetime import datetime
from typing import Dict, List, Optional, Any
from loguru import logger
import pymongo
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
import json

class DashboardDBHelper:
    """
    Helper class to store message data for the admin dashboard
    This is a separate database from the main conversation history
    Focused on storing data that will be useful for monitoring conversations
    """
    def __init__(self, connection_string: Optional[str] = None, db_name: Optional[str] = None):
        """Initialize MongoDB connection for dashboard"""
        # Use environment variables as defaults if not provided
        if connection_string is None:
            connection_string = os.getenv("DASHBOARD_DB_URI")
        if db_name is None:
            db_name = os.getenv("DASHBOARD_DB_NAME", "instagram_dashboard")
            
        try:
            if not connection_string:
                logger.warning("No dashboard database connection string provided, dashboard updates will be disabled")
                self.client = None
                return
                
            # Connect to MongoDB
            self.client = MongoClient(connection_string)
            self.db: Database = self.client[db_name]
            
            # Create collections for dashboard data
            self.messages: Collection = self.db["messages"]  # All messages (user and bot)
            self.threads: Collection = self.db["threads"]    # Thread metadata
            self.stats: Collection = self.db["stats"]        # Usage statistics
            
            # Create indexes
            self.messages.create_index([("thread_id", pymongo.ASCENDING), ("timestamp", pymongo.DESCENDING)])
            self.messages.create_index([("is_from_bot", pymongo.ASCENDING)])
            self.messages.create_index([("timestamp", pymongo.DESCENDING)])
            self.threads.create_index([("thread_id", pymongo.ASCENDING)], unique=True)
            self.threads.create_index([("last_active", pymongo.DESCENDING)])
            
            logger.info(f"Connected to dashboard database: {db_name}")
        except Exception as e:
            logger.error(f"Failed to connect to dashboard database: {e}")
            self.client = None
            logger.warning("Dashboard updates will be disabled")
    
    def is_connected(self) -> bool:
        """Check if MongoDB is connected"""
        return self.client is not None
    
    def store_message(self, thread_id: str, username: str, text: str, is_from_bot: bool, 
                      message_id: Optional[str] = None) -> bool:
        """
        Store a message in the dashboard database
        
        Args:
            thread_id: Instagram thread ID
            username: Instagram username of the user
            text: Content of the message
            is_from_bot: Whether the message is from the bot or user
            message_id: Optional original message ID from Instagram
            
        Returns:
            True if successful, False otherwise
        """
        if not self.is_connected():
            return False
            
        try:
            timestamp = datetime.now()
            
            # Prepare message document
            message_data = {
                "thread_id": thread_id,
                "username": username,
                "text": text,
                "is_from_bot": is_from_bot,
                "timestamp": timestamp,
                "message_id": message_id or f"dash_{int(time.time())}",
            }
            
            # Insert message
            self.messages.insert_one(message_data)
            
            # Update thread metadata
            self.threads.update_one(
                {"thread_id": thread_id},
                {
                    "$set": {
                        "username": username,
                        "last_active": timestamp,
                        "last_message": text[:100] + ("..." if len(text) > 100 else ""),
                        "last_message_from_bot": is_from_bot
                    },
                    "$inc": {"message_count": 1}
                },
                upsert=True
            )
            
            # Update global stats
            self.stats.update_one(
                {"stat_id": "global"},
                {
                    "$inc": {
                        "total_messages": 1,
                        "bot_messages" if is_from_bot else "user_messages": 1
                    },
                    "$set": {"last_updated": timestamp}
                },
                upsert=True
            )
            
            # Update daily stats
            day_key = timestamp.strftime("%Y-%m-%d")
            self.stats.update_one(
                {"stat_id": f"daily_{day_key}"},
                {
                    "$inc": {
                        "total_messages": 1,
                        "bot_messages" if is_from_bot else "user_messages": 1
                    },
                    "$set": {"date": day_key, "last_updated": timestamp}
                },
                upsert=True
            )
            
            logger.debug(f"Stored message in dashboard DB - Thread: {thread_id}, User: {username}, Bot: {is_from_bot}")
            return True
        except Exception as e:
            logger.error(f"Error storing message in dashboard database: {e}")
            return False
    
    def update_thread_status(self, thread_id: str, username: str, status: str) -> bool:
        """
        Update thread status in the dashboard database
        
        Args:
            thread_id: Instagram thread ID
            username: Instagram username
            status: Thread status (e.g., 'active', 'pending', 'closed')
            
        Returns:
            True if successful, False otherwise
        """
        if not self.is_connected():
            return False
            
        try:
            self.threads.update_one(
                {"thread_id": thread_id},
                {
                    "$set": {
                        "username": username,
                        "status": status,
                        "status_updated": datetime.now()
                    }
                },
                upsert=True
            )
            return True
        except Exception as e:
            logger.error(f"Error updating thread status in dashboard database: {e}")
            return False
    
    def record_api_call(self, api_type: str, success: bool) -> bool:
        """
        Record API call statistics
        
        Args:
            api_type: Type of API call ('instagram', 'chatgpt', etc.)
            success: Whether the API call was successful
            
        Returns:
            True if successful, False otherwise
        """
        if not self.is_connected():
            return False
            
        try:
            timestamp = datetime.now()
            day_key = timestamp.strftime("%Y-%m-%d")
            
            # Update global API stats
            self.stats.update_one(
                {"stat_id": f"api_{api_type}"},
                {
                    "$inc": {
                        "total_calls": 1,
                        "successful_calls" if success else "failed_calls": 1
                    },
                    "$set": {"last_updated": timestamp}
                },
                upsert=True
            )
            
            # Update daily API stats
            self.stats.update_one(
                {"stat_id": f"api_{api_type}_{day_key}"},
                {
                    "$inc": {
                        "total_calls": 1,
                        "successful_calls" if success else "failed_calls": 1
                    },
                    "$set": {"date": day_key, "last_updated": timestamp}
                },
                upsert=True
            )
            
            return True
        except Exception as e:
            logger.error(f"Error recording API call in dashboard database: {e}")
            return False 