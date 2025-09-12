"""
Database optimization modules for eliminating N+1 queries
"""

from .batch_operations import BatchOptimizations, OPTIMIZED_INDEXES

__all__ = ['BatchOptimizations', 'OPTIMIZED_INDEXES']