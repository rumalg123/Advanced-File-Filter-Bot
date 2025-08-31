"""
Unified session management system
Consolidates duplicate session tracking implementations
"""

import asyncio
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, UTC
from enum import Enum
from typing import Optional, Dict, Any, List

from core.cache.config import CacheTTLConfig
from core.utils.logger import get_logger

logger = get_logger(__name__)


class SessionType(Enum):
    """Types of user sessions"""
    EDIT = "edit"
    SEARCH = "search"
    INDEX = "index"
    BATCH = "batch"


class SessionStatus(Enum):
    """Session status states"""
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


@dataclass
class SessionData:
    """Unified session data structure"""
    user_id: int
    session_type: SessionType
    session_id: str
    status: SessionStatus
    created_at: datetime
    expires_at: datetime
    last_activity: datetime
    data: Dict[str, Any]
    
    def is_expired(self) -> bool:
        """Check if session is expired"""
        return datetime.now(UTC) > self.expires_at
    
    def is_active(self) -> bool:
        """Check if session is active and not expired"""
        return self.status == SessionStatus.ACTIVE and not self.is_expired()
    
    def update_activity(self):
        """Update last activity timestamp"""
        self.last_activity = datetime.now(UTC)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for caching"""
        data = asdict(self)
        data['created_at'] = self.created_at.isoformat()
        data['expires_at'] = self.expires_at.isoformat()
        data['last_activity'] = self.last_activity.isoformat()
        data['session_type'] = self.session_type.value
        data['status'] = self.status.value
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SessionData':
        """Create from dictionary"""
        data['created_at'] = datetime.fromisoformat(data['created_at'])
        data['expires_at'] = datetime.fromisoformat(data['expires_at'])
        data['last_activity'] = datetime.fromisoformat(data['last_activity'])
        data['session_type'] = SessionType(data['session_type'])
        data['status'] = SessionStatus(data['status'])
        return cls(**data)


class UnifiedSessionManager:
    """Unified session management system"""
    
    # Default TTL values for different session types
    DEFAULT_TTL = {
        SessionType.EDIT: 300,      # 5 minutes
        SessionType.SEARCH: 3600,   # 1 hour
        SessionType.INDEX: 1800,    # 30 minutes
        SessionType.BATCH: 7200,    # 2 hours
    }
    
    def __init__(self, cache_manager):
        self.cache = cache_manager
        self.ttl_config = CacheTTLConfig()
        self._cleanup_task = None
        self._shutdown_event = asyncio.Event()
        
    async def start_cleanup_task(self):
        """Start the background cleanup task"""
        if not self._cleanup_task:
            self._cleanup_task = asyncio.create_task(self._cleanup_expired_sessions())
    
    async def stop_cleanup_task(self):
        """Stop the background cleanup task"""
        if self._cleanup_task:
            self._shutdown_event.set()
            try:
                await asyncio.wait_for(self._cleanup_task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("Session cleanup task did not stop gracefully")
                self._cleanup_task.cancel()
            finally:
                self._cleanup_task = None
    
    def _generate_cache_key(self, session_type: SessionType, user_id: int, session_id: Optional[str] = None) -> str:
        """Generate cache key for session"""
        if session_id:
            return f"session:{session_type.value}:{user_id}:{session_id}"
        else:
            return f"session:{session_type.value}:{user_id}"
    
    async def create_session(
        self,
        user_id: int,
        session_type: SessionType,
        data: Dict[str, Any],
        session_id: Optional[str] = None,
        ttl_override: Optional[int] = None
    ) -> str:
        """
        Create a new session
        Returns: session_id
        """
        if not session_id:
            session_id = f"{user_id}_{int(time.time())}_{session_type.value}"
        
        # Cancel any existing session of the same type for this user
        await self.cancel_session(user_id, session_type)
        
        # Calculate expiration time
        ttl = ttl_override or self.DEFAULT_TTL.get(session_type, 300)
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=ttl)
        
        # Create session data
        session = SessionData(
            user_id=user_id,
            session_type=session_type,
            session_id=session_id,
            status=SessionStatus.ACTIVE,
            created_at=now,
            expires_at=expires_at,
            last_activity=now,
            data=data
        )
        
        # Cache the session
        cache_key = self._generate_cache_key(session_type, user_id, session_id)
        await self.cache.set(cache_key, session.to_dict(), expire=ttl)
        
        # Also cache with just user_id for quick lookups
        user_cache_key = self._generate_cache_key(session_type, user_id)
        await self.cache.set(user_cache_key, session_id, expire=ttl)
        
        logger.debug(f"Created {session_type.value} session {session_id} for user {user_id}")
        return session_id
    
    async def get_session(
        self,
        user_id: int,
        session_type: SessionType,
        session_id: Optional[str] = None
    ) -> Optional[SessionData]:
        """Get session data"""
        try:
            if not session_id:
                # Get session ID from cache
                user_cache_key = self._generate_cache_key(session_type, user_id)
                session_id = await self.cache.get(user_cache_key)
                if not session_id:
                    return None
            
            # Get full session data
            cache_key = self._generate_cache_key(session_type, user_id, session_id)
            session_data = await self.cache.get(cache_key)
            
            if not session_data:
                return None
            
            session = SessionData.from_dict(session_data)
            
            # Check if expired
            if session.is_expired():
                await self.cancel_session(user_id, session_type, session_id)
                return None
            
            return session
            
        except Exception as e:
            logger.error(f"Error getting session: {e}")
            return None
    
    async def update_session(
        self,
        user_id: int,
        session_type: SessionType,
        data: Dict[str, Any],
        session_id: Optional[str] = None
    ) -> bool:
        """Update session data"""
        try:
            session = await self.get_session(user_id, session_type, session_id)
            if not session:
                return False
            
            # Update data and activity
            session.data.update(data)
            session.update_activity()
            
            # Save back to cache
            cache_key = self._generate_cache_key(session_type, user_id, session.session_id)
            ttl = int((session.expires_at - datetime.now(UTC)).total_seconds())
            if ttl > 0:
                await self.cache.set(cache_key, session.to_dict(), expire=ttl)
                return True
            else:
                # Session expired during update
                await self.cancel_session(user_id, session_type, session.session_id)
                return False
                
        except Exception as e:
            logger.error(f"Error updating session: {e}")
            return False
    
    async def extend_session(
        self,
        user_id: int,
        session_type: SessionType,
        extension_seconds: int,
        session_id: Optional[str] = None
    ) -> bool:
        """Extend session expiration time"""
        try:
            session = await self.get_session(user_id, session_type, session_id)
            if not session:
                return False
            
            # Extend expiration
            session.expires_at += timedelta(seconds=extension_seconds)
            session.update_activity()
            
            # Save back to cache
            cache_key = self._generate_cache_key(session_type, user_id, session.session_id)
            new_ttl = int((session.expires_at - datetime.now(UTC)).total_seconds())
            if new_ttl > 0:
                await self.cache.set(cache_key, session.to_dict(), expire=new_ttl)
                # Also update user cache key
                user_cache_key = self._generate_cache_key(session_type, user_id)
                await self.cache.set(user_cache_key, session.session_id, expire=new_ttl)
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error extending session: {e}")
            return False
    
    async def cancel_session(
        self,
        user_id: int,
        session_type: SessionType,
        session_id: Optional[str] = None
    ) -> bool:
        """Cancel/delete a session"""
        try:
            if not session_id:
                # Get session ID from cache
                user_cache_key = self._generate_cache_key(session_type, user_id)
                session_id = await self.cache.get(user_cache_key)
                if not session_id:
                    return True  # Already gone
                # Delete user cache key
                await self.cache.delete(user_cache_key)
            
            # Delete full session data
            cache_key = self._generate_cache_key(session_type, user_id, session_id)
            await self.cache.delete(cache_key)
            
            # Also delete user cache key if not done already
            user_cache_key = self._generate_cache_key(session_type, user_id)
            await self.cache.delete(user_cache_key)
            
            logger.debug(f"Cancelled {session_type.value} session {session_id} for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error cancelling session: {e}")
            return False
    
    async def has_active_session(self, user_id: int, session_type: SessionType) -> bool:
        """Check if user has an active session of given type"""
        session = await self.get_session(user_id, session_type)
        return session is not None and session.is_active()
    
    async def get_user_sessions(self, user_id: int) -> List[SessionData]:
        """Get all active sessions for a user"""
        sessions = []
        
        for session_type in SessionType:
            session = await self.get_session(user_id, session_type)
            if session and session.is_active():
                sessions.append(session)
        
        return sessions
    
    async def cancel_all_user_sessions(self, user_id: int) -> int:
        """Cancel all sessions for a user"""
        cancelled = 0
        
        for session_type in SessionType:
            if await self.cancel_session(user_id, session_type):
                cancelled += 1
        
        return cancelled
    
    async def get_session_stats(self) -> Dict[str, Any]:
        """Get session statistics"""
        stats: Dict[str, Any] = {
            'active_sessions': {},
            'total_active': 0
        }
        
        try:
            # This is a simplified implementation
            # In a real scenario, you might want to scan cache keys
            # but that could be expensive, so we'll just return basic info
            for session_type in SessionType:
                stats['active_sessions'][session_type.value] = 0
            
            # Could implement more detailed stats if needed
            stats['cache_info'] = await self.cache.get_cache_stats() if hasattr(self.cache, 'get_cache_stats') else {}
            
        except Exception as e:
            logger.error(f"Error getting session stats: {e}")
            stats['error'] = str(e)
        
        return stats
    
    async def _cleanup_expired_sessions(self):
        """Background task to cleanup expired sessions"""
        while not self._shutdown_event.is_set():
            try:
                # Wait for either shutdown or cleanup interval
                cleanup_interval = 300  # 5 minutes
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=cleanup_interval
                )
                break  # Shutdown requested
                
            except asyncio.TimeoutError:
                # Time to cleanup
                try:
                    # Use pattern deletion to clean up expired sessions
                    deleted = await self.cache.delete_pattern("session:*")
                    if deleted > 0:
                        logger.info(f"Cleaned up {deleted} expired session cache entries")
                except Exception as e:
                    logger.error(f"Error during session cleanup: {e}")
    
    # Backward compatibility methods for existing code
    
    async def create_edit_session(self, user_id: int, data: Dict[str, Any]) -> str:
        """Create edit session (backward compatibility)"""
        return await self.create_session(user_id, SessionType.EDIT, data)
    
    async def get_edit_session(self, user_id: int) -> Optional[SessionData]:
        """Get edit session (backward compatibility)"""
        return await self.get_session(user_id, SessionType.EDIT)
    
    async def cancel_edit_session(self, user_id: int) -> bool:
        """Cancel edit session (backward compatibility)"""
        return await self.cancel_session(user_id, SessionType.EDIT)
    
    async def create_search_session(self, user_id: int, session_id: str, data: Dict[str, Any]) -> str:
        """Create search session (backward compatibility)"""
        return await self.create_session(user_id, SessionType.SEARCH, data, session_id)
    
    async def get_search_session(self, user_id: int, session_id: str) -> Optional[SessionData]:
        """Get search session (backward compatibility)"""
        return await self.get_session(user_id, SessionType.SEARCH, session_id)
    
    async def cancel_search_session(self, user_id: int, session_id: str) -> bool:
        """Cancel search session (backward compatibility)"""
        return await self.cancel_session(user_id, SessionType.SEARCH, session_id)