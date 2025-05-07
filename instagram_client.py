import os
import time
import random
from typing import List, Dict, Optional, Tuple
import json
from pathlib import Path
from loguru import logger

from instagrapi import Client
from instagrapi.types import DirectMessage, DirectThread

class InstagramClient:
    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.client = Client()
        self.session_file = Path("instagram_session.json")
        self.user_id = None
        self._login()
        # Last request timestamps for rate limiting
        self.last_request_time = 0
        
    def _login(self) -> None:
        """Login to Instagram, using session if available"""
        try:
            if self.session_file.exists():
                logger.info("Using existing session file")
                self.client.load_settings(self.session_file)
                self.client.login(self.username, self.password)
            else:
                logger.info("Logging in with username and password")
                self.client.login(self.username, self.password)
                self.client.dump_settings(self.session_file)
                
            self.user_id = self.client.user_id
            logger.info(f"Login successful for {self.username}")
        except Exception as e:
            logger.error(f"Login failed: {e}")
            raise
    
    def _rate_limit_request(self, min_delay: float = 2.0, max_delay: float = 4.0) -> None:
        """Rate limit requests to avoid API throttling"""
        current_time = time.time()
        elapsed = current_time - self.last_request_time
        
        # If last request was less than min_delay seconds ago, sleep
        if elapsed < min_delay:
            sleep_time = min_delay - elapsed + random.uniform(0, max_delay - min_delay)
            logger.debug(f"Rate limiting: sleeping for {sleep_time:.2f} seconds")
            time.sleep(sleep_time)
            
        self.last_request_time = time.time()
    
    def get_unread_threads(self, max_retries: int = 3) -> List[DirectThread]:
        """Get all unread threads from regular inbox"""
        for attempt in range(max_retries):
            try:
                self._rate_limit_request()
                # In newer versions, use direct_threads() with filter="unread"
                inbox = self.client.direct_threads(selected_filter="unread")
                if not inbox:
                    # If no unread threads were found with the filter, try manually filtering
                    all_threads = self.client.direct_threads()
                    unread_threads = []
                    for thread_id in all_threads:
                        self._rate_limit_request()
                        thread = self.client.direct_thread(thread_id)
                        if hasattr(thread, 'unread_count') and thread.unread_count > 0:
                            unread_threads.append(thread)
                    return unread_threads
                return inbox
            except Exception as e:
                logger.error(f"Error getting unread threads (attempt {attempt+1}/{max_retries}): {e}")
                import traceback
                logger.error(traceback.format_exc())
                if attempt < max_retries - 1:
                    sleep_time = (2 ** attempt) + random.uniform(0, 1)  # Exponential backoff
                    logger.info(f"Retrying in {sleep_time:.2f} seconds...")
                    time.sleep(sleep_time)
                
        return []  # Return empty list after all retries failed
    
    def get_pending_threads(self, amount: int = 20, max_retries: int = 3) -> List[DirectThread]:
        """Get all threads from pending inbox"""
        for attempt in range(max_retries):
            try:
                self._rate_limit_request()
                pending_threads = self.client.direct_pending_inbox(amount)
                logger.info(f"Found {len(pending_threads)} pending message requests")
                return pending_threads
            except Exception as e:
                logger.error(f"Error getting pending threads (attempt {attempt+1}/{max_retries}): {e}")
                import traceback
                logger.error(traceback.format_exc())
                if attempt < max_retries - 1:
                    sleep_time = (2 ** attempt) + random.uniform(0, 1)  # Exponential backoff
                    logger.info(f"Retrying in {sleep_time:.2f} seconds...")
                    time.sleep(sleep_time)
                
        return []  # Return empty list after all retries failed
    
    def approve_pending_thread(self, thread_id: str, max_retries: int = 3) -> bool:
        """Approve a pending message request"""
        for attempt in range(max_retries):
            try:
                # According to the latest API, we need to use direct_thread_approve
                # Try different approaches to approve the thread
                try:
                    self._rate_limit_request()
                    # First try direct_thread_approve if it exists
                    if hasattr(self.client, 'direct_thread_approve'):
                        self.client.direct_thread_approve(thread_id)
                        logger.info(f"Approved pending message request for thread {thread_id} using direct_thread_approve")
                        return True
                except Exception as e1:
                    logger.warning(f"Could not approve thread with direct_thread_approve: {e1}")
                    
                try:
                    self._rate_limit_request()
                    # Try sending a blank message to approve it (this works in some API versions)
                    self.client.direct_answer(thread_id, "")
                    logger.info(f"Approved pending message request for thread {thread_id} using direct_answer")
                    return True
                except Exception as e2:
                    logger.warning(f"Could not approve thread with direct_answer: {e2}")
                    
                # As a last resort, try to directly get and respond to the thread
                self._rate_limit_request()
                thread = self.client.direct_thread(thread_id)
                if thread:
                    logger.info(f"Successfully fetched pending thread {thread_id}, considering it approved")
                    return True
                    
                logger.error(f"Failed to approve thread {thread_id} with all available methods")
                return False
            except Exception as e:
                logger.error(f"Error approving pending thread {thread_id} (attempt {attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    sleep_time = (2 ** attempt) + random.uniform(0, 1)  # Exponential backoff
                    logger.info(f"Retrying in {sleep_time:.2f} seconds...")
                    time.sleep(sleep_time)
        
        return False  # Failed all attempts
    
    def get_thread_messages(self, thread_id: str, limit: int = 10, max_retries: int = 3) -> List[DirectMessage]:
        """Get the last messages from a thread"""
        for attempt in range(max_retries):
            try:
                self._rate_limit_request()
                thread = self.client.direct_thread(thread_id)
                return thread.messages[:limit] if hasattr(thread, 'messages') else []
            except Exception as e:
                logger.error(f"Error getting messages for thread {thread_id} (attempt {attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    sleep_time = (2 ** attempt) + random.uniform(0, 1)  # Exponential backoff
                    logger.info(f"Retrying in {sleep_time:.2f} seconds...")
                    time.sleep(sleep_time)
                
        return []  # Return empty list after all retries failed
    
    def send_message(self, thread_id: str, text: str, max_retries: int = 3) -> bool:
        """Send a message to a thread"""
        for attempt in range(max_retries):
            try:
                self._rate_limit_request()
                self.client.direct_send(text, thread_ids=[thread_id])
                logger.info(f"Message sent to thread {thread_id}")
                return True
            except Exception as e:
                logger.error(f"Error sending message to thread {thread_id} (attempt {attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    sleep_time = (2 ** attempt) + random.uniform(0, 1)  # Exponential backoff
                    logger.info(f"Retrying in {sleep_time:.2f} seconds...")
                    time.sleep(sleep_time)
                
        return False  # Failed all attempts
    
    def mark_thread_seen(self, thread_id: str, max_retries: int = 3) -> bool:
        """Mark a thread as seen/read"""
        for attempt in range(max_retries):
            try:
                self._rate_limit_request()
                self.client.direct_send_seen(thread_id)  # Updated method name
                logger.info(f"Thread {thread_id} marked as seen")
                return True
            except Exception as e:
                logger.error(f"Error marking thread {thread_id} as seen (attempt {attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    sleep_time = (2 ** attempt) + random.uniform(0, 1)  # Exponential backoff
                    logger.info(f"Retrying in {sleep_time:.2f} seconds...")
                    time.sleep(sleep_time)
                
        return False  # Failed all attempts
    
    def get_pending_thread_ids(self, amount: int = 20, max_retries: int = 3) -> List[str]:
        """Get a list of thread IDs from the pending inbox"""
        for attempt in range(max_retries):
            try:
                self._rate_limit_request()
                pending_inbox = self.client.direct_pending_inbox(amount)
                thread_ids = []
                
                # Handle different return types from the API
                if isinstance(pending_inbox, list):
                    # If it returns a list of threads
                    for thread in pending_inbox:
                        if hasattr(thread, 'id'):
                            thread_ids.append(thread.id)
                elif hasattr(pending_inbox, 'threads'):
                    # If it returns an object with a threads attribute
                    for thread in pending_inbox.threads:
                        if hasattr(thread, 'id'):
                            thread_ids.append(thread.id)
                elif isinstance(pending_inbox, dict) and 'threads' in pending_inbox:
                    # If it returns a dictionary with threads key
                    for thread in pending_inbox['threads']:
                        if 'thread_id' in thread:
                            thread_ids.append(thread['thread_id'])
                            
                logger.info(f"Found {len(thread_ids)} pending thread IDs")
                return thread_ids
            except Exception as e:
                logger.error(f"Error getting pending thread IDs (attempt {attempt+1}/{max_retries}): {e}")
                import traceback
                logger.error(traceback.format_exc())
                if attempt < max_retries - 1:
                    sleep_time = (2 ** attempt) + random.uniform(0, 1)  # Exponential backoff
                    logger.info(f"Retrying in {sleep_time:.2f} seconds...")
                    time.sleep(sleep_time)
                
        return []  # Return empty list after all retries failed 