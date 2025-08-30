"""
File emoji utilities for displaying appropriate emojis based on file types
"""

import os
from typing import Optional
from repositories.media import FileType


def get_file_emoji(file_type: FileType, file_name: str, mime_type: Optional[str] = None) -> str:
    """
    Get appropriate emoji based primarily on file extension, with file type as fallback
    
    Args:
        file_type: The FileType enum value from Telegram
        file_name: The file name to check extension
        mime_type: The MIME type of the file
        
    Returns:
        str: Appropriate emoji for the file type
    """
    # Handle both formats: "movie.mp4" and "movie mp4" (sanitized)
    file_extension = os.path.splitext(file_name.lower())[1].lower()
    
    # If no extension found with splitext (due to sanitization), extract from end of filename
    if not file_extension:
        # Check if filename ends with common extensions (without dot)
        words = file_name.lower().split()
        if words:
            last_word = words[-1]
            # Check if last word looks like a file extension (3-4 characters)
            if len(last_word) in [2, 3, 4, 5] and last_word.isalnum():
                file_extension = '.' + last_word
    
    # PRIORITY 1: Check by file extension first (most reliable)
    # This handles cases where Telegram misclassifies files as "document"
    
    # Video files by extension
    if file_extension in ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.3gp', '.ts', '.mpg', '.mpeg', '.vob', '.rm', '.rmvb', '.asf', '.f4v', '.ogv']:
        return "🎬"
    
    # Audio files by extension
    elif file_extension in ['.mp3', '.flac', '.wav', '.aac', '.ogg', '.wma', '.m4a', '.opus', '.ape', '.aiff', '.au', '.ra']:
        return "🎵"
    
    # Image files by extension
    elif file_extension in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg', '.tiff', '.tif', '.ico', '.heic', '.heif', '.raw', '.cr2', '.nef', '.dng', '.psd', '.ai', '.eps', '.sketch']:
        # Special case for GIF (could be animation)
        if file_extension == '.gif':
            return "🎭"
        else:
            return "🖼️"
    
    # Archive/Compressed files
    elif file_extension in ['.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.xz', '.apk', '.ipa', '.deb', '.rpm', '.pkg', '.dmg', '.msi', '.cab', '.ace', '.lzh', '.arj', '.z', '.jar', '.war', '.ear']:
        return "📦"
    
    # Subtitle files
    elif file_extension in ['.srt', '.vtt', '.ass', '.ssa', '.sub', '.sbv', '.dfxp', '.ttml', '.lrc', '.smi', '.rt', '.scc']:
        return "💬"
    
    # PDF files
    elif file_extension == '.pdf':
        return "📄"
    
    # Text files
    elif file_extension in ['.txt', '.md', '.log', '.cfg', '.conf', '.ini', '.json', '.xml', '.yaml', '.yml', '.csv', '.tsv', '.rtf']:
        return "📝"
    
    # Excel/Spreadsheet files
    elif file_extension in ['.xlsx', '.xls', '.ods', '.xlsm', '.xlsb', '.xltx', '.xltm']:
        return "📊"
    
    # PowerPoint/Presentation files
    elif file_extension in ['.pptx', '.ppt', '.odp', '.pps', '.ppsx', '.potx', '.key']:
        return "📈"
    
    # Word/Document files
    elif file_extension in ['.docx', '.doc', '.odt', '.pages', '.dotx', '.dotm']:
        return "📄"
    
    # Code/Programming files
    elif file_extension in ['.py', '.js', '.html', '.css', '.cpp', '.c', '.java', '.php', '.rb', '.go', '.rs', '.ts', '.jsx', '.tsx', '.vue', '.swift', '.kt', '.cs', '.vb', '.sql', '.sh', '.bat', '.ps1']:
        return "💻"
    
    # Database files
    elif file_extension in ['.db', '.sqlite', '.sqlite3', '.mdb', '.accdb', '.dbf']:
        return "🗄️"
    
    # Font files
    elif file_extension in ['.ttf', '.otf', '.woff', '.woff2', '.eot', '.pfb', '.pfm']:
        return "🔤"
    
    # Ebook files
    elif file_extension in ['.epub', '.mobi', '.azw', '.azw3', '.fb2', '.lit', '.pdb', '.cbr', '.cbz']:
        return "📚"
    
    # 3D model files
    elif file_extension in ['.obj', '.fbx', '.dae', '.3ds', '.blend', '.max', '.maya', '.c4d', '.ply', '.stl']:
        return "🎲"
    
    # Executable files
    elif file_extension in ['.exe', '.com', '.scr', '.bat', '.cmd', '.ps1', '.sh', '.run', '.app']:
        return "⚙️"
    
    # Certificate/Security files
    elif file_extension in ['.cert', '.crt', '.pem', '.key', '.p12', '.pfx', '.der', '.cer', '.p7b', '.p7c']:
        return "🔒"
    
    # ISO/Disk image files
    elif file_extension in ['.iso', '.img', '.vdi', '.vmdk', '.vhd', '.qcow2', '.bin', '.cue']:
        return "💿"
    
    # Torrent files
    elif file_extension == '.torrent':
        return "🔗"
    
    # CAD files
    elif file_extension in ['.dwg', '.dxf', '.step', '.iges', '.sat', '.x_t']:
        return "📐"
    
    # Video project files
    elif file_extension in ['.prproj', '.aep', '.fcpx', '.veg', '.camproj']:
        return "🎞️"
    
    # PRIORITY 2: If extension didn't match, fall back to Telegram's file type
    # This ensures we don't miss any files that have unusual extensions
    
    # Video files (fallback)
    elif file_type == FileType.VIDEO:
        return "🎬"
    
    # Audio files (fallback)
    elif file_type == FileType.AUDIO:
        return "🎵"
    
    # Photo/Image files (fallback)
    elif file_type == FileType.PHOTO:
        return "🖼️"
    
    # Animation files (fallback)
    elif file_type == FileType.ANIMATION:
        return "🎭"
    
    # Document and application files (fallback for unknown extensions)
    elif file_type in [FileType.DOCUMENT, FileType.APPLICATION]:
        return "📄"  # Generic document icon for unknown file types
    
    # Fallback to folder emoji for unknown types
    return "📁"


def get_file_type_display_name(file_type: FileType) -> str:
    """
    Get human-readable display name for file type
    
    Args:
        file_type: The FileType enum value
        
    Returns:
        str: Human-readable file type name
    """
    type_names = {
        FileType.VIDEO: "Video",
        FileType.AUDIO: "Audio", 
        FileType.DOCUMENT: "Document",
        FileType.PHOTO: "Image",
        FileType.ANIMATION: "Animation",
        FileType.APPLICATION: "Application"
    }
    
    return type_names.get(file_type, "File")