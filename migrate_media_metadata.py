#!/usr/bin/env python3
"""
Migration script to backfill season/episode/resolution fields for existing media files.

This script:
- Processes all documents in media_files collection
- Extracts season/episode/resolution from file_name and caption
- Updates documents where these fields are missing/null
- Processes in batches for efficiency
- Shows progress and statistics

Usage:
    python migrate_media_metadata.py [--batch-size BATCH_SIZE] [--dry-run] [--limit LIMIT]
    
Options:
    --batch-size: Number of documents to process per batch (default: 1000)
    --dry-run: Show what would be updated without making changes
    --limit: Limit number of documents to process (for testing)
"""

import asyncio
import argparse
import sys
from typing import Dict, Any, Optional
from datetime import datetime

# Add project root to path
sys.path.insert(0, '.')

from core.database.pool import DatabaseConnectionPool
from core.cache.redis_cache import CacheManager
from core.utils.helpers import parse_media_metadata
from core.utils.logger import get_logger

logger = get_logger(__name__)


class MediaMetadataMigration:
    """Migration script for backfilling media metadata fields"""
    
    def __init__(self, db_pool: DatabaseConnectionPool, batch_size: int = 1000):
        self.db_pool = db_pool
        self.batch_size = batch_size
        self.stats = {
            'total': 0,
            'processed': 0,
            'updated': 0,
            'skipped': 0,
            'errors': 0
        }
    
    async def run(self, dry_run: bool = False, limit: Optional[int] = None):
        """Run the migration"""
        logger.info("=" * 60)
        logger.info("Media Metadata Migration Script")
        logger.info("=" * 60)
        logger.info(f"Batch size: {self.batch_size}")
        logger.info(f"Dry run: {dry_run}")
        if limit:
            logger.info(f"Limit: {limit} documents")
        logger.info("=" * 60)
        
        try:
            collection = await self.db_pool.get_collection('media_files')
            
            # Count total documents
            total_count = await self.db_pool.execute_with_retry(
                collection.count_documents, {}
            )
            self.stats['total'] = total_count
            logger.info(f"Total documents in media_files: {total_count}")
            
            if limit:
                total_count = min(total_count, limit)
                logger.info(f"Processing limited to: {total_count} documents")
            
            # Process in batches
            processed = 0
            skip = 0
            
            while processed < total_count:
                batch_limit = min(self.batch_size, total_count - processed)
                
                # Fetch batch
                cursor = collection.find({}).skip(skip).limit(batch_limit)
                batch = await self.db_pool.execute_with_retry(
                    cursor.to_list, length=batch_limit
                )
                
                if not batch:
                    break
                
                # Process batch
                batch_updated = await self._process_batch(
                    collection, batch, dry_run
                )
                
                processed += len(batch)
                skip += len(batch)
                self.stats['processed'] = processed
                self.stats['updated'] += batch_updated
                
                # Progress update
                progress_pct = (processed / total_count) * 100
                logger.info(
                    f"Progress: {processed}/{total_count} ({progress_pct:.1f}%) | "
                    f"Updated: {self.stats['updated']} | "
                    f"Skipped: {self.stats['skipped']} | "
                    f"Errors: {self.stats['errors']}"
                )
                
                # Small delay to avoid overwhelming the database
                await asyncio.sleep(0.1)
            
            # Final summary
            logger.info("=" * 60)
            logger.info("Migration Complete!")
            logger.info("=" * 60)
            logger.info(f"Total documents: {self.stats['total']}")
            logger.info(f"Processed: {self.stats['processed']}")
            logger.info(f"Updated: {self.stats['updated']}")
            logger.info(f"Skipped: {self.stats['skipped']}")
            logger.info(f"Errors: {self.stats['errors']}")
            logger.info("=" * 60)
            
        except Exception as e:
            logger.error(f"Migration failed: {e}", exc_info=True)
            raise
    
    async def _process_batch(
        self,
        collection,
        batch: list,
        dry_run: bool
    ) -> int:
        """Process a batch of documents"""
        updates = []
        batch_updated = 0
        
        for doc in batch:
            try:
                # Check if document needs updating
                needs_update = (
                    not doc.get('season') and
                    not doc.get('episode') and
                    not doc.get('resolution')
                )
                
                # Also update if any field is null
                if not needs_update:
                    needs_update = (
                        doc.get('season') is None or
                        doc.get('episode') is None or
                        doc.get('resolution') is None
                    )
                
                if not needs_update:
                    self.stats['skipped'] += 1
                    continue
                
                # Extract metadata from file_name and caption
                file_name = doc.get('file_name', '')
                caption = doc.get('caption', '')
                
                # Remove HTML tags from caption if present
                if caption:
                    import re
                    caption = re.sub(r'<[^>]+>', '', caption)
                
                season, episode, resolution = parse_media_metadata(
                    file_name, caption
                )
                
                # Only update if we found something
                if season or episode or resolution:
                    update_data = {}
                    if season and not doc.get('season'):
                        update_data['season'] = season
                    if episode and not doc.get('episode'):
                        update_data['episode'] = episode
                    if resolution and not doc.get('resolution'):
                        update_data['resolution'] = resolution
                    
                    if update_data:
                        update_data['updated_at'] = datetime.utcnow().isoformat()
                        
                        if dry_run:
                            logger.debug(
                                f"[DRY RUN] Would update {doc.get('_id', 'unknown')}: "
                                f"{update_data}"
                            )
                            batch_updated += 1
                        else:
                            # Prepare update operation
                            updates.append({
                                'filter': {'_id': doc['_id']},
                                'update': {'$set': update_data}
                            })
                            batch_updated += 1
                else:
                    self.stats['skipped'] += 1
                    
            except Exception as e:
                logger.error(f"Error processing document {doc.get('_id', 'unknown')}: {e}")
                self.stats['errors'] += 1
        
        # Execute batch update
        if updates and not dry_run:
            try:
                from pymongo import UpdateOne
                operations = [
                    UpdateOne(item['filter'], item['update'])
                    for item in updates
                ]
                
                if operations:
                    result = await self.db_pool.execute_with_retry(
                        collection.bulk_write, operations
                    )
                    logger.debug(
                        f"Batch update: {result.modified_count} documents updated"
                    )
            except Exception as e:
                logger.error(f"Error executing batch update: {e}")
                self.stats['errors'] += len(updates)
                batch_updated = 0
        
        return batch_updated


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Migrate media files to add season/episode/resolution fields'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=1000,
        help='Number of documents to process per batch (default: 1000)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be updated without making changes'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Limit number of documents to process (for testing)'
    )
    
    args = parser.parse_args()
    
    # Initialize database connection
    # Note: This script should be run with the same environment as the bot
    # Make sure .env file is loaded or environment variables are set
    try:
        from config.settings import settings
        
        db_pool = DatabaseConnectionPool()
        await db_pool.initialize(
            settings.database.uri,
            settings.database.name
        )
        logger.info("Database connection initialized")
        
        # Initialize cache (not strictly needed for migration, but for consistency)
        cache = CacheManager(settings.redis.uri if settings.redis.uri else None)
        await cache.initialize()
        logger.info("Cache initialized")
        
        # Run migration
        migration = MediaMetadataMigration(db_pool, batch_size=args.batch_size)
        await migration.run(dry_run=args.dry_run, limit=args.limit)
        
        logger.info("Migration script completed successfully")
        
    except KeyboardInterrupt:
        logger.info("Migration interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        sys.exit(1)
    finally:
        # Cleanup
        if 'db_pool' in locals():
            await db_pool.close()
        if 'cache' in locals():
            await cache.close()


if __name__ == '__main__':
    asyncio.run(main())
