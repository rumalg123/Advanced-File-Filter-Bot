# core/utils/pagination.py
from typing import List, Optional, Tuple
from pyrogram.types import InlineKeyboardButton


class PaginationBuilder:
    """Smart pagination builder with dynamic page range display"""

    def __init__(self,
                 total_items: int,
                 page_size: int,
                 current_offset: int,
                 query: str,
                 user_id: int,
                 callback_prefix: str = "search",
                 max_visible_pages: int = 11):
        """
        Initialize pagination builder

        Args:
            total_items: Total number of items
            page_size: Items per page
            current_offset: Current offset in results
            query: Search query string
            user_id: User ID for callback data
            callback_prefix: Prefix for callback data (e.g., "search", "filter")
            max_visible_pages: Maximum number of page buttons to show (default 11)
        """
        self.total_items = total_items
        self.page_size = page_size
        self.current_offset = current_offset
        self.query = query
        self.user_id = user_id
        self.callback_prefix = callback_prefix
        self.max_visible_pages = max_visible_pages

        # Calculate page info
        self.current_page = (current_offset // page_size) + 1
        self.total_pages = ((total_items - 1) // page_size) + 1 if total_items > 0 else 1

    def _get_page_range(self) -> Tuple[int, int]:
        """
        Calculate the range of page numbers to display
        Returns tuple of (start_page, end_page) inclusive
        """
        if self.total_pages <= self.max_visible_pages:
            # Show all pages if total is less than max visible
            return 1, self.total_pages

        # Calculate the range centered around current page
        half_visible = self.max_visible_pages // 2

        # Start with current page in the middle
        start_page = self.current_page - half_visible
        end_page = self.current_page + half_visible

        # Adjust if we're near the beginning
        if start_page < 1:
            start_page = 1
            end_page = min(self.max_visible_pages, self.total_pages)

        # Adjust if we're near the end
        elif end_page > self.total_pages:
            end_page = self.total_pages
            start_page = max(1, self.total_pages - self.max_visible_pages + 1)

        return start_page, end_page

    def _create_callback_data(self, action: str, offset: Optional[int] = None) -> str:
        """Create callback data string"""
        if action == "noop":
            return f"noop#{self.user_id}"

        if offset is None:
            # Calculate offset based on action
            if action == "first":
                offset = 0
            elif action == "last":
                offset = ((self.total_pages - 1) * self.page_size)
            elif action == "prev":
                offset = max(0, self.current_offset - self.page_size)
            elif action == "next":
                offset = min(self.current_offset + self.page_size,
                             (self.total_pages - 1) * self.page_size)
            else:
                offset = self.current_offset

        return f"{self.callback_prefix}#{action}#{self.query}#{offset}#{self.total_items}#{self.user_id}"

    def build_pagination_buttons(self) -> List[List[InlineKeyboardButton]]:
        """
        Build smart pagination buttons with dynamic page range

        Returns:
            List of button rows for pagination
        """
        buttons = []

        # First row: Navigation buttons (First, Prev, Current/Total, Next, Last)
        nav_row = []

        # First page button (only show if not on first page)
        if self.current_page > 1:
            nav_row.append(
                InlineKeyboardButton(
                    "⏮ First",
                    callback_data=self._create_callback_data("first")
                )
            )

        # Previous button (only show if not on first page)
        if self.current_page > 1:
            nav_row.append(
                InlineKeyboardButton(
                    "◀️ Prev",
                    callback_data=self._create_callback_data("prev")
                )
            )

        # Current page indicator (always shown)
        nav_row.append(
            InlineKeyboardButton(
                f"📄 {self.current_page}/{self.total_pages}",
                callback_data=self._create_callback_data("noop")
            )
        )

        # Next button (only show if not on last page)
        if self.current_page < self.total_pages:
            nav_row.append(
                InlineKeyboardButton(
                    "Next ▶️",
                    callback_data=self._create_callback_data("next")
                )
            )

        # Last page button (only show if not on last page)
        if self.current_page < self.total_pages:
            nav_row.append(
                InlineKeyboardButton(
                    "Last ⏭",
                    callback_data=self._create_callback_data("last")
                )
            )

        buttons.append(nav_row)

        # Second row: Page number buttons (if more than 1 page)
        if self.total_pages > 1:
            page_row = []
            start_page, end_page = self._get_page_range()

            # Add ellipsis at the beginning if needed
            if start_page > 1:
                page_row.append(
                    InlineKeyboardButton(
                        "...",
                        callback_data=self._create_callback_data("noop")
                    )
                )

            # Add page number buttons
            for page_num in range(start_page, end_page + 1):
                page_offset = (page_num - 1) * self.page_size

                # Highlight current page
                if page_num == self.current_page:
                    button_text = f"[{page_num}]"
                else:
                    button_text = str(page_num)

                page_row.append(
                    InlineKeyboardButton(
                        button_text,
                        callback_data=self._create_callback_data("page", page_offset)
                    )
                )

            # Add ellipsis at the end if needed
            if end_page < self.total_pages:
                page_row.append(
                    InlineKeyboardButton(
                        "...",
                        callback_data=self._create_callback_data("noop")
                    )
                )

            buttons.append(page_row)

        return buttons

    def build_simple_pagination(self) -> List[InlineKeyboardButton]:
        """
        Build simple pagination row (single row with nav buttons only)
        Used when space is limited

        Returns:
            List of navigation buttons for a single row
        """
        nav_buttons = []

        # First and Previous buttons
        if self.current_page > 1:
            nav_buttons.append(
                InlineKeyboardButton(
                    "⏮ First",
                    callback_data=self._create_callback_data("first")
                )
            )
            nav_buttons.append(
                InlineKeyboardButton(
                    "◀️ Prev",
                    callback_data=self._create_callback_data("prev")
                )
            )

        # Current page indicator
        nav_buttons.append(
            InlineKeyboardButton(
                f"📄 {self.current_page}/{self.total_pages}",
                callback_data=self._create_callback_data("noop")
            )
        )

        # Next and Last buttons
        if self.current_page < self.total_pages:
            nav_buttons.append(
                InlineKeyboardButton(
                    "Next ▶️",
                    callback_data=self._create_callback_data("next")
                )
            )
            nav_buttons.append(
                InlineKeyboardButton(
                    "Last ⏭",
                    callback_data=self._create_callback_data("last")
                )
            )

        return nav_buttons


class PaginationHelper:
    """Helper methods for pagination-related operations"""

    @staticmethod
    def parse_callback_data(callback_data: str) -> dict|None:
        """
        Parse pagination callback data

        Args:
            callback_data: Callback data string

        Returns:
            Dictionary with parsed values or None if invalid
        """
        parts = callback_data.split("#")

        # Handle new format with user_id
        if len(parts) >= 6:
            return {
                'prefix': parts[0],
                'action': parts[1],
                'query': parts[2],
                'offset': int(parts[3]),
                'total': int(parts[4]),
                'user_id': int(parts[5])
            }

        # Handle old format without user_id
        elif len(parts) >= 5:
            return {
                'prefix': parts[0],
                'action': parts[1],
                'query': parts[2],
                'offset': int(parts[3]),
                'total': int(parts[4]),
                'user_id': None
            }

        return None

    @staticmethod
    def calculate_new_offset(action: str, current_offset: int, page_size: int, total: int) -> int:
        """
        Calculate new offset based on action

        Args:
            action: Navigation action (first, prev, next, last, page)
            current_offset: Current offset
            page_size: Items per page
            total: Total items

        Returns:
            New offset value
        """
        if action == "first":
            return 0
        elif action == "prev":
            return max(0, current_offset - page_size)
        elif action == "next":
            max_offset = ((total - 1) // page_size) * page_size
            return min(current_offset + page_size, max_offset)
        elif action == "last":
            return ((total - 1) // page_size) * page_size
        elif action == "page":
            # For direct page navigation, offset should be passed separately
            return current_offset
        else:
            return current_offset