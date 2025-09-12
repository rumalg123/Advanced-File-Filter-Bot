# verify_alignment.py - Fixed script to verify bot and manager alignment

import logging
from typing import Dict

logger = logging.getLogger(__name__)


class AlignmentVerifier:
    """Verify that bot and HandlerManager are properly aligned"""

    def __init__(self, bot):
        self.bot = bot
        self.issues = []
        self.warnings = []
        self.successes = []

    async def verify_all(self) -> Dict:
        """Run all verification checks"""
        checks = [
            self.check_handler_manager_exists,
            self.check_handler_instances,
            self.check_background_tasks,
            self.check_handler_registration,
            self.check_cleanup_methods,
            self.check_task_tracking,
            self.check_shutdown_signals
        ]

        for check in checks:
            try:
                await check()
            except Exception as e:
                self.issues.append(f"Check {check.__name__} failed: {e}")

        return {
            "issues": self.issues,
            "warnings": self.warnings,
            "successes": self.successes,
            "is_aligned": len(self.issues) == 0,
            "health_score": self._calculate_health_score()
        }

    async def check_handler_manager_exists(self):
        """Check if HandlerManager is properly initialized"""
        if not hasattr(self.bot, 'handler_manager'):
            self.issues.append("Bot does not have handler_manager attribute")
            return

        if self.bot.handler_manager is None:
            self.issues.append("handler_manager is None")
            return

        self.successes.append("✓ HandlerManager is properly initialized")

    async def check_handler_instances(self):
        """Check if handlers are registered in manager"""
        if not self.bot.handler_manager:
            return

        expected_handlers = [
            'command', 'search', 'delete', 'channel',
            'indexing', 'filestore', 'request'
        ]

        if not self.bot.config.DISABLE_FILTER:
            expected_handlers.extend(['filter', 'connection'])

        registered = list(self.bot.handler_manager.handler_instances.keys())

        for handler in expected_handlers:
            if handler not in registered:
                self.warnings.append(f"Handler '{handler}' not registered in manager")
            else:
                self.successes.append(f"✓ Handler '{handler}' is registered")

        # Check for unexpected handlers
        for handler in registered:
            if handler not in expected_handlers:
                self.warnings.append(f"Unexpected handler '{handler}' in manager")

    async def check_background_tasks(self):
        """Check background task tracking"""
        if not self.bot.handler_manager:
            return

        stats = self.bot.handler_manager.get_stats()

        if stats['background_tasks'] == 0:
            self.warnings.append("No background tasks registered")
        else:
            self.successes.append(f"✓ {stats['background_tasks']} background tasks tracked")

        # Check for specific expected tasks
        expected_tasks = ['maintenance_tasks']
        named_tasks = list(self.bot.handler_manager.named_tasks.keys())

        for task in expected_tasks:
            if task not in named_tasks:
                self.warnings.append(f"Expected task '{task}' not found")
            else:
                task_obj = self.bot.handler_manager.named_tasks[task]
                if not task_obj.done():
                    self.successes.append(f"✓ Task '{task}' is running")
                else:
                    self.warnings.append(f"Task '{task}' is not running")

    async def check_handler_registration(self):
        """Check if handlers are using manager for registration"""
        if not self.bot.handler_manager:
            return

        for name, handler in self.bot.handler_manager.handler_instances.items():
            if hasattr(handler, '_handlers'):
                handler_count = len(handler._handlers)
                if handler_count > 0:
                    self.successes.append(f"✓ {name} has {handler_count} handlers registered")
                else:
                    self.warnings.append(f"{name} has no handlers registered")

    async def check_cleanup_methods(self):
        """Check if all handlers have cleanup methods"""
        if not self.bot.handler_manager:
            return

        for name, handler in self.bot.handler_manager.handler_instances.items():
            if hasattr(handler, 'cleanup'):
                self.successes.append(f"✓ {name} has cleanup method")
            else:
                self.issues.append(f"{name} missing cleanup method")

    async def check_task_tracking(self):
        """Check task creation and completion stats"""
        if not self.bot.handler_manager:
            return

        stats = self.bot.handler_manager.get_stats()

        if stats['total_created'] > 0:
            completion_rate = 0
            if stats['total_created'] > 0:
                completion_rate = stats['total_completed'] / stats['total_created'] * 100

            self.successes.append(
                f"✓ Task tracking working: {stats['total_created']} created, "
                f"{stats['total_completed']} completed ({completion_rate:.1f}%)"
            )

        # Check for task leaks
        active_tasks = (
                stats['background_tasks'] +
                stats['auto_delete_tasks'] +
                stats['named_tasks']  # This is already an integer!
        )

        expected_max_tasks = 50  # Adjust based on your needs
        if active_tasks > expected_max_tasks:
            self.warnings.append(f"High number of active tasks: {active_tasks}")

    async def check_shutdown_signals(self):
        """Check if shutdown signals are properly set up"""
        if not self.bot.handler_manager:
            return

        for name, handler in self.bot.handler_manager.handler_instances.items():
            if hasattr(handler, '_shutdown'):
                self.successes.append(f"✓ {name} has shutdown signal")
            else:
                self.warnings.append(f"{name} missing shutdown signal")

    def _calculate_health_score(self) -> int:
        """Calculate overall health score (0-100)"""
        total_checks = len(self.issues) + len(self.warnings) + len(self.successes)
        if total_checks == 0:
            return 0

        # Issues are critical (-10 points each)
        # Warnings are minor (-3 points each)
        # Successes are +5 points each
        score = 50  # Base score
        score -= len(self.issues) * 10
        score -= len(self.warnings) * 3
        score += len(self.successes) * 5

        # Normalize to 0-100
        return max(0, min(100, score))


# Fixed command to properly handle stats
async def verify_alignment_command(client, message):
    """Admin command to verify bot-manager alignment"""
    status_msg = await message.reply_text("🔍 Verifying bot-manager alignment...")

    try:
        # Get the bot instance correctly
        bot = client  # In a command handler, client IS the bot

        verifier = AlignmentVerifier(bot)
        results = await verifier.verify_all()

        # Format results
        text = "<b>🔧 Bot-Manager Alignment Report</b>\n\n"

        text += f"<b>Health Score:</b> {results['health_score']}/100 "
        if results['health_score'] >= 80:
            text += "✅\n\n"
        elif results['health_score'] >= 60:
            text += "⚠️\n\n"
        else:
            text += "❌\n\n"

        if results['successes']:
            text += f"<b>✅ Successes ({len(results['successes'])}):</b>\n"
            for success in results['successes'][:10]:  # Limit to 10
                text += f"  {success}\n"
            if len(results['successes']) > 10:
                text += f"  ... and {len(results['successes']) - 10} more\n"
            text += "\n"

        if results['warnings']:
            text += f"<b>⚠️ Warnings ({len(results['warnings'])}):</b>\n"
            for warning in results['warnings'][:5]:
                text += f"  • {warning}\n"
            if len(results['warnings']) > 5:
                text += f"  ... and {len(results['warnings']) - 5} more\n"
            text += "\n"

        if results['issues']:
            text += f"<b>❌ Issues ({len(results['issues'])}):</b>\n"
            for issue in results['issues']:
                text += f"  • {issue}\n"
            text += "\n"

        # Add manager stats - FIXED section
        if hasattr(bot, 'handler_manager') and bot.handler_manager:
            stats = bot.handler_manager.get_stats()
            text += "<b>📊 Manager Statistics:</b>\n"
            text += f"  • Handlers: {stats['handlers_active']}\n"
            text += f"  • Handler Instances: {stats['handler_instances']}\n"
            text += f"  • Background Tasks: {stats['background_tasks']}\n"
            text += f"  • Auto-Delete Tasks: {stats['auto_delete_tasks']}\n"
            text += f"  • Named Tasks: {stats['named_tasks']}\n"  # Already an integer!
            text += f"  • Tasks Created: {stats['total_created']}\n"
            text += f"  • Tasks Completed: {stats['total_completed']}\n"
            text += f"  • Tasks Cancelled: {stats['total_cancelled']}\n"

            # Get list of named tasks if you want to show them
            if bot.handler_manager.named_tasks:
                text += "\n<b>📝 Named Tasks:</b>\n"
                for task_name, task in bot.handler_manager.named_tasks.items():
                    status = "✅ Running" if not task.done() else "⏹ Completed"
                    text += f"  • {task_name}: {status}\n"

        await status_msg.edit_text(text)

    except Exception as e:
        logger.error(f"Verification failed: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Verification failed: {str(e)}")

