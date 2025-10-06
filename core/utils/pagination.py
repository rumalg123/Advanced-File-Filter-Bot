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
                 max_visible_pages: int = 8,
                 boundary_pages: int = 1,
                 surrounding_pages: int = 1):
        """
        Initialize pagination builder with React-style pagination

        Args:
            total_items: Total number of items
            page_size: Items per page
            current_offset: Current offset in results
            query: Search query string
            user_id: User ID for callback data
            callback_prefix: Prefix for callback data (e.g., "search", "filter")
            max_visible_pages: Maximum number of page buttons to show (default 8 - Telegram limit)
            boundary_pages: Number of pages to show at start and end (default 1)
            surrounding_pages: Number of pages to show around current page (default 1)
        """
        self.total_items = total_items
        self.page_size = page_size
        self.current_offset = current_offset
        self.query = query
        self.user_id = user_id
        self.callback_prefix = callback_prefix
        self.max_visible_pages = max_visible_pages
        self.boundary_pages = boundary_pages  # Pages to show at beginning and end
        self.surrounding_pages = surrounding_pages  # Pages to show around current

        # Calculate page info
        self.current_page = (current_offset // page_size) + 1
        self.total_pages = ((total_items - 1) // page_size) + 1 if total_items > 0 else 1

    def _get_page_numbers(self) -> List[Optional[int]]:
        """
        Calculate page numbers to display with React-style pagination
        Returns list of page numbers with None representing ellipsis

        Strictly ensures the result fits within Telegram's button limit (8 buttons per row)
        """
        if self.total_pages <= self.max_visible_pages:
            # Show all pages if total is less than max visible
            return list(range(1, self.total_pages + 1))

        pages = []
        max_buttons = self.max_visible_pages

        # We'll use a simple approach: always show first, last, current and nearby pages
        # Pattern: [1] ... [current-1] [current] [current+1] ... [last]

        # Always include page 1
        pages.append(1)

        # Determine range around current page
        if self.current_page <= 3:
            # Near beginning: show pages 1-5, then ellipsis, then last page
            for i in range(2, min(6, self.total_pages)):
                pages.append(i)
            if self.total_pages > 6:
                pages.append(None)  # ellipsis
                pages.append(self.total_pages)

        elif self.current_page >= self.total_pages - 2:
            # Near end: show first page, ellipsis, then last 5 pages
            if self.total_pages > 6:
                pages.append(None)  # ellipsis
            for i in range(max(2, self.total_pages - 4), self.total_pages + 1):
                pages.append(i)

        else:
            # In middle: 1 ... current-1 current current+1 ... last
            pages.append(None)  # ellipsis before

            # Add page before current (if not page 2)
            if self.current_page > 2:
                pages.append(self.current_page - 1)

            pages.append(self.current_page)  # current page

            # Add page after current (if not second to last)
            if self.current_page < self.total_pages - 1:
                pages.append(self.current_page + 1)

            pages.append(None)  # ellipsis after
            pages.append(self.total_pages)  # last page

        # Final safety check - ensure we never exceed max_buttons
        while len(pages) > max_buttons:
            # Find a non-essential page to remove
            for i in range(1, len(pages) - 1):
                if pages[i] not in [1, self.current_page, self.total_pages, None]:
                    pages.pop(i)
                    break
            else:
                # If we can't find any page to remove, break
                break

        return pages

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
        Build smart pagination buttons with React-style dynamic page range

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

        # Second row: Page number buttons (if more than 1 page) with React-style pagination
        if self.total_pages > 1:
            page_row = []
            page_numbers = self._get_page_numbers()

            for page_item in page_numbers:
                if page_item is None:
                    # Add ellipsis
                    page_row.append(
                        InlineKeyboardButton(
                            "...",
                            callback_data=self._create_callback_data("noop")
                        )
                    )
                else:
                    page_offset = (page_item - 1) * self.page_size

                    # Highlight current page
                    if page_item == self.current_page:
                        button_text = f"[{page_item}]"
                    else:
                        button_text = str(page_item)

                    page_row.append(
                        InlineKeyboardButton(
                            button_text,
                            callback_data=self._create_callback_data("page", page_offset)
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