import asyncio
import psutil
import time
from typing import Dict, Any
import sys
from datetime import datetime, UTC


class PerformanceMonitor:
    """Monitor performance metrics with uvloop awareness"""

    def __init__(self):
        self.start_time = time.time()
        # Keep a single Process instance so cpu_percent() has a previous sample.
        self.process = psutil.Process()
        # Prime CPU counters to avoid persistent 0.0 on first reads.
        self.process.cpu_percent(None)
        psutil.cpu_percent(None)

    async def get_metrics(self) -> Dict[str, Any]:
        """Get current performance metrics"""
        using_uvloop = False
        event_loop_type = 'asyncio'

        # Get event loop info
        try:
            loop = asyncio.get_running_loop()
            loop_class_name = loop.__class__.__module__
            if 'uvloop' in loop_class_name:
                using_uvloop = True
                event_loop_type = 'uvloop'
        except RuntimeError:
            # Fallback to checking sys.modules
            if 'uvloop' in sys.modules:
                using_uvloop = True
                event_loop_type = 'uvloop'

        rss_mb = self.process.memory_info().rss / 1024 / 1024
        vms_mb = self.process.memory_info().vms / 1024 / 1024
        process_cpu = self.process.cpu_percent(None)
        system_cpu = psutil.cpu_percent(None)
        virtual_memory = psutil.virtual_memory()

        metrics = {
            'event_loop': event_loop_type,
            'uptime_seconds': time.time() - self.start_time,
            'sampled_at_utc': datetime.now(UTC).isoformat(),
            'process_memory_rss_mb': rss_mb,
            'process_memory_vms_mb': vms_mb,
            'process_memory_percent': self.process.memory_percent(),
            'system_memory_percent': virtual_memory.percent,
            'process_cpu_percent': process_cpu,
            'system_cpu_percent': system_cpu,
            'num_threads': self.process.num_threads(),
            'num_fds': self.process.num_fds() if hasattr(self.process, 'num_fds') else 0,
            'pending_tasks': len(asyncio.all_tasks()),
            'data_freshness': {
                'is_cached': False,
                'cpu_sampling_mode': 'delta_since_last_call'
            }
        }

        # uvloop specific optimizations
        if using_uvloop:
            metrics['optimization'] = 'High Performance Mode'
            metrics['expected_improvement'] = '2-4x throughput'
        else:
            metrics['optimization'] = 'Standard Mode'
            metrics['recommendation'] = 'Install uvloop for better performance'

        return metrics


performance_monitor = PerformanceMonitor()
