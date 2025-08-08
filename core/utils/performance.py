# core/utils/performance.py - New file for performance monitoring

import asyncio
import psutil
import time
from typing import Dict, Any
import sys


class PerformanceMonitor:
    """Monitor performance metrics with uvloop awareness"""

    def __init__(self):
        self.start_time = time.time()
        #self.using_uvloop = 'uvloop' in sys.modules

    async def get_metrics(self) -> Dict[str, Any]:
        """Get current performance metrics"""
        process = psutil.Process()
        using_uvloop = False
        event_loop_type = 'asyncio'

        # Get event loop info
        try:
            loop = asyncio.get_running_loop()
            loop_class_name = loop.__class__.__module__
            if 'uvloop' in loop_class_name:
                using_uvloop = True
                event_loop_type = 'uvloop'
        except:
            # Fallback to checking sys.modules
            if 'uvloop' in sys.modules:
                using_uvloop = True
                event_loop_type = 'uvloop'

        metrics = {
            'event_loop': event_loop_type,
            'uptime_seconds': time.time() - self.start_time,
            'memory_mb': process.memory_info().rss / 1024 / 1024,
            'cpu_percent': process.cpu_percent(),
            'num_threads': process.num_threads(),
            'num_fds': process.num_fds() if hasattr(process, 'num_fds') else 0,
            'pending_tasks': len(asyncio.all_tasks()),
        }

        # uvloop specific optimizations
        if using_uvloop:
            metrics['optimization'] = 'High Performance Mode'
            metrics['expected_improvement'] = '2-4x throughput'
        else:
            metrics['optimization'] = 'Standard Mode'
            metrics['recommendation'] = 'Install uvloop for better performance'

        return metrics


# Add to bot.py initialization
performance_monitor = PerformanceMonitor()