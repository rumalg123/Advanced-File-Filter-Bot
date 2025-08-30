"""
File emoji utilities for displaying appropriate emojis based on file types
"""

import os
from typing import Optional
from repositories.media import FileType


def get_file_emoji(file_type: FileType, file_name: str, mime_type: Optional[str] = None) -> str:
    """
    Get appropriate emoji based on file type, file name, and mime type
    
    Args:
        file_type: The FileType enum value
        file_name: The file name to check extension
        mime_type: The MIME type of the file
        
    Returns:
        str: Appropriate emoji for the file type
    """
    file_extension = os.path.splitext(file_name.lower())[1].lower()
    
    # Video files
    if file_type == FileType.VIDEO:
        return "🎬"
    
    # Audio files
    elif file_type == FileType.AUDIO:
        return "🎵"
    
    # Photo/Image files
    elif file_type == FileType.PHOTO:
        return "🖼️"
    
    # Animation files (GIF, etc.)
    elif file_type == FileType.ANIMATION:
        return "🎭"
    
    # Document and application files - check by extension
    elif file_type in [FileType.DOCUMENT, FileType.APPLICATION]:
        # Archive/Compressed files
        if file_extension in ['.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.xz', '.apk', '.ipa']:
            return "📦"
        
        # Subtitle files
        elif file_extension in ['.srt', '.vtt', '.ass', '.ssa', '.sub', '.sbv', '.dfxp', '.ttml']:
            return "💬"
        
        # PDF files
        elif file_extension == '.pdf':
            return "📄"
        
        # Text files
        elif file_extension in ['.txt', '.md', '.log', '.cfg', '.conf', '.ini', '.json', '.xml', '.yaml', '.yml']:
            return "📝"
        
        # Excel/Spreadsheet files
        elif file_extension in ['.xlsx', '.xls', '.csv', '.ods']:
            return "📊"
        
        # PowerPoint/Presentation files
        elif file_extension in ['.pptx', '.ppt', '.odp']:
            return "📈"
        
        # Word/Document files
        elif file_extension in ['.docx', '.doc', '.odt', '.rtf']:
            return "📄"
        
        # Image files (additional formats)
        elif file_extension in ['.svg', '.eps', '.ai', '.psd', '.sketch']:
            return "🎨"
        
        # Code/Programming files
        elif file_extension in ['.py', '.js', '.html', '.css', '.cpp', '.c', '.java', '.php', '.rb', '.go', '.rs']:
            return "💻"
        
        # Database files
        elif file_extension in ['.db', '.sqlite', '.sql', '.mdb']:
            return "🗄️"
        
        # Font files
        elif file_extension in ['.ttf', '.otf', '.woff', '.woff2', '.eot']:
            return "🔤"
        
        # Ebook files
        elif file_extension in ['.epub', '.mobi', '.azw', '.azw3', '.fb2']:
            return "📚"
        
        # 3D model files
        elif file_extension in ['.obj', '.fbx', '.dae', '.3ds', '.blend', '.max']:
            return "🎲"
        
        # Executable files
        elif file_extension in ['.exe', '.msi', '.deb', '.rpm', '.dmg', '.pkg']:
            return "⚙️"
        
        # Certificate/Security files
        elif file_extension in ['.cert', '.crt', '.pem', '.key', '.p12', '.pfx']:
            return "🔒"
        
        # ISO/Disk image files
        elif file_extension in ['.iso', '.img', '.dmg', '.vdi', '.vmdk']:
            return "💿"
        
        # Torrent files
        elif file_extension == '.torrent':
            return "🔗"
        
        # Default document emoji for unknown document types
        else:
            return "📄"
    
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