# Refactoring Opportunities Analysis

## 🔍 Current Codebase Analysis

Based on code review, here are the key refactoring opportunities:

---

## 1. **MediaFile Factory Pattern** (HIGH PRIORITY)

### Problem
`MediaFile` objects are created with **identical logic** in 3+ places:
- `core/services/indexing.py:267-277`
- `core/services/filestore.py:176-188`
- `handlers/channel.py:408-420`

**Duplicated logic:**
- Extract file_name, normalize it
- Parse season/episode/resolution from filename + caption
- Get resolution from media.width/height or parsed value
- Determine file_type from Pyrogram media type
- Extract file_ref

### Solution
Create a `MediaFileFactory` class:

```python
# core/utils/media_factory.py
class MediaFileFactory:
    @staticmethod
    def from_pyrogram_media(
        media: Any,  # Pyrogram media object
        message: Message,
        file_type_enum: Optional[FileType] = None
    ) -> MediaFile:
        """Create MediaFile from Pyrogram media object"""
        # Centralized logic here
```

**Benefits:**
- Single source of truth for MediaFile creation
- Easier to maintain and update
- Consistent behavior across all creation points
- ~50 lines of code eliminated

---

## 2. **Search Results Sender Duplication** (HIGH PRIORITY)

### Problem
`_send_search_results()` method is **duplicated** in:
- `handlers/search.py:537-665` (91 lines)
- `handlers/request.py:203-351` (148 lines)

**Duplicated logic:**
- Session ID generation
- Cache storage
- Pagination building
- Button creation
- Caption formatting
- Message sending with photo/text

### Solution
Extract to shared service or base class:

```python
# core/services/search_results.py
class SearchResultsService:
    async def send_results(
        self,
        client: Client,
        message: Message,
        files: List[MediaFile],
        query: str,
        total: int,
        user_id: int,
        is_private: bool,
        config: Any
    ) -> bool:
        """Unified search results sender"""
```

**Benefits:**
- ~150 lines of duplicate code eliminated
- Consistent UI/UX across search and request handlers
- Single place to update result formatting

---

## 3. **File Type Conversion Utility** (MEDIUM PRIORITY)

### Problem
File type conversion logic duplicated:
- `core/services/indexing.py:360-369` - `_get_file_type()`
- `handlers/channel.py` - Similar logic
- `core/services/filestore.py` - Inline conversion

### Solution
Create centralized utility:

```python
# core/utils/file_type.py
def get_file_type_from_pyrogram(
    media_type: enums.MessageMediaType
) -> FileType:
    """Convert Pyrogram MessageMediaType to FileType enum"""
    # Centralized mapping
```

**Benefits:**
- Consistent type conversion
- Easier to extend with new types
- ~20 lines eliminated

---

## 4. **Media Extraction Utility** (MEDIUM PRIORITY)

### Problem
Media extraction from messages is duplicated:
- `handlers/channel.py:382-390` - Loops through media types
- `core/services/filestore.py:136-142` - Similar extraction
- `core/utils/helpers.py:extract_file_info()` - Different pattern

### Solution
Enhance existing `extract_file_info()` or create unified extractor:

```python
# core/utils/media_extractor.py
class MediaExtractor:
    @staticmethod
    def extract_from_message(message: Message) -> Optional[MediaInfo]:
        """Extract media from message with consistent pattern"""
```

**Benefits:**
- Single extraction pattern
- Consistent error handling
- Easier to test

---

## 5. **Search Filter Builder Enhancement** (LOW PRIORITY)

### Problem
`_build_search_filter()` in `repositories/media.py` is getting complex (65 lines) and handles multiple concerns:
- Query parsing
- Regex building
- Filter combination
- Metadata filtering

### Solution
Split into smaller, focused methods:

```python
def _build_search_filter(...):
    # Delegate to smaller methods
    text_filter = self._build_text_filter(...)
    metadata_filter = self._build_metadata_filter(...)
    return self._combine_filters(text_filter, metadata_filter, file_type)
```

**Benefits:**
- Better testability
- Clearer separation of concerns
- Easier to extend

---

## 6. **Error Response Standardization** (MEDIUM PRIORITY)

### Problem
While error handling is standardized, **error messages** are still inconsistent:
- Some use emoji prefixes: `"❌ Error: ..."`
- Some use plain text: `"Error: ..."`
- Some use HTML: `"<b>Error</b>: ..."`
- Different error detail levels

### Solution
Create error message formatter:

```python
# core/utils/error_formatter.py
class ErrorMessageFormatter:
    @staticmethod
    def format_error(message: str, include_details: bool = True) -> str:
        """Format error messages consistently"""
        return f"❌ <b>Error:</b> {message}"
```

**Benefits:**
- Consistent user experience
- Easier to update error styling
- Better localization support

---

## 7. **Button Builder Pattern** (LOW PRIORITY)

### Problem
Inline keyboard button creation is scattered:
- Search results buttons
- Pagination buttons
- Filter buttons
- File buttons
- All have similar patterns but different implementations

### Solution
Create button builder utilities:

```python
# core/utils/button_builder.py
class ButtonBuilder:
    @staticmethod
    def file_button(file: MediaFile, callback_data: str) -> InlineKeyboardButton:
        """Create standardized file button"""
    
    @staticmethod
    def send_all_button(count: int, callback_data: str) -> List[InlineKeyboardButton]:
        """Create send all button"""
```

**Benefits:**
- Consistent button formatting
- Easier to update UI
- Reusable components

---

## 8. **Caption Formatting Consolidation** (MEDIUM PRIORITY)

### Problem
Caption formatting logic exists in:
- `core/utils/caption.py` - `CaptionFormatter`
- `handlers/search.py` - Inline caption building
- `handlers/request.py` - Similar inline building

### Solution
Extend `CaptionFormatter` to handle all cases or create unified formatter.

**Benefits:**
- Consistent captions
- Single place to update formatting

---

## 9. **Repository Query Builder** (LOW PRIORITY)

### Problem
Complex MongoDB queries are built inline:
- `_build_search_filter()` builds complex `$and`/`$or` structures
- Similar patterns in other repositories

### Solution
Create query builder pattern:

```python
# core/database/query_builder.py
class QueryBuilder:
    def text_search(self, query: str) -> 'QueryBuilder':
        """Add text search to query"""
    
    def metadata_filter(self, season, episode, resolution) -> 'QueryBuilder':
        """Add metadata filters"""
    
    def build(self) -> Dict[str, Any]:
        """Build final MongoDB query"""
```

**Benefits:**
- More readable query construction
- Easier to test
- Reusable across repositories

---

## 10. **Service Layer Consolidation** (LOW PRIORITY)

### Problem
Some services have overlapping responsibilities:
- `FileAccessService` - File access + search
- `FileStoreService` - File storage + link generation
- Could be better organized

### Solution
Consider splitting or reorganizing:
- `FileSearchService` - Search operations
- `FileStorageService` - Storage operations
- `FileLinkService` - Link generation

**Benefits:**
- Clearer responsibilities
- Better testability
- Easier to maintain

---

## Implementation Priority

### Phase 1: High Impact, Low Risk
1. ✅ **MediaFile Factory** - Eliminates most duplication
2. ✅ **Search Results Sender** - Large code reduction

### Phase 2: Medium Impact
3. ✅ **File Type Conversion** - Simple utility
4. ✅ **Media Extraction** - Enhance existing utility
5. ✅ **Error Message Formatting** - Consistency improvement

### Phase 3: Code Quality
6. ✅ **Search Filter Builder** - Better organization
7. ✅ **Button Builder** - UI consistency
8. ✅ **Caption Formatting** - Consolidation

### Phase 4: Architecture
9. ✅ **Query Builder** - Advanced pattern
10. ✅ **Service Reorganization** - Larger refactor

---

## Estimated Impact

### Code Reduction
- **MediaFile Factory**: ~50 lines eliminated
- **Search Results Sender**: ~150 lines eliminated
- **File Type Utility**: ~20 lines eliminated
- **Total**: ~220 lines of duplicate code removed

### Maintainability
- **Single source of truth** for common operations
- **Easier testing** with focused utilities
- **Consistent behavior** across codebase

### Risk Level
- **Phase 1-2**: Low risk (extract existing code)
- **Phase 3**: Medium risk (refactor existing patterns)
- **Phase 4**: Higher risk (architectural changes)

---

## Testing Strategy

For each refactoring:
1. **Extract to utility/service** (new file)
2. **Update all call sites** to use new utility
3. **Run existing tests** to verify behavior
4. **Add unit tests** for new utilities
5. **Integration tests** for critical paths

---

## Notes

- All refactorings maintain **backward compatibility**
- No functional changes, only code organization
- Can be done incrementally (one at a time)
- Each refactoring is independently testable
