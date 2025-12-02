"use client";

// Configuration for cache management
const CACHE_CONFIG = {
  MAX_CACHE_SIZE_MB: 3, // Maximum cache size in MB (reduced to prevent quota issues)
  MAX_ENTRIES: 25, // Maximum number of cache entries (reduced for table data)
  MAX_AGE_MS: 3 * 24 * 60 * 60 * 1000, // 3 days in milliseconds (reduced from 7)
  CLEANUP_THRESHOLD: 0.7, // Start cleanup when cache is 70% full (more aggressive)
};

interface CacheEntry {
  value: any;
  lastAccessed: number;
  size: number; // Approximate size in bytes
}

interface CacheMetadata {
  entries: Record<string, { lastAccessed: number; size: number }>;
  totalSize: number;
}

/**
 * Estimates the size of a value in bytes
 */
function estimateSize(value: any): number {
  try {
    return new Blob([JSON.stringify(value)]).size;
  } catch {
    // Fallback: rough estimate
    return JSON.stringify(value).length * 2;
  }
}

/**
 * Loads metadata from localStorage
 */
function loadMetadata(): CacheMetadata {
  try {
    const stored = localStorage.getItem("app-cache-metadata");
    if (stored) {
      return JSON.parse(stored);
    }
  } catch (error) {
    console.warn("[Cache] Failed to load metadata:", error);
  }
  return { entries: {}, totalSize: 0 };
}

/**
 * Saves metadata to localStorage
 */
function saveMetadata(metadata: CacheMetadata): void {
  try {
    localStorage.setItem("app-cache-metadata", JSON.stringify(metadata));
  } catch (error) {
    console.warn("[Cache] Failed to save metadata:", error);
  }
}

/**
 * Removes old or least recently used entries to free up space
 */
function evictEntries(
  map: Map<any, CacheEntry>,
  metadata: CacheMetadata,
  targetSizeReduction: number,
): void {
  const now = Date.now();
  const entries = Array.from(map.entries());

  // Sort by last accessed time (oldest first)
  entries.sort((a, b) => a[1].lastAccessed - b[1].lastAccessed);

  let freedSpace = 0;
  const keysToDelete: any[] = [];

  for (const [key, entry] of entries) {
    // Remove expired entries
    if (now - entry.lastAccessed > CACHE_CONFIG.MAX_AGE_MS) {
      keysToDelete.push(key);
      freedSpace += entry.size;
      continue;
    }

    // Remove LRU entries if we need more space
    if (freedSpace < targetSizeReduction) {
      keysToDelete.push(key);
      freedSpace += entry.size;
    } else {
      break;
    }
  }

  // Delete the selected entries
  for (const key of keysToDelete) {
    const normalizedKey = typeof key === "string" ? key : JSON.stringify(key);
    map.delete(key);
    delete metadata.entries[normalizedKey];
  }

  metadata.totalSize = Math.max(0, metadata.totalSize - freedSpace);

  console.log(
    `[Cache] Evicted ${keysToDelete.length} entries, freed ${(freedSpace / 1024 / 1024).toFixed(2)} MB`,
  );
}

/**
 * Checks if cache needs cleanup and performs eviction if necessary
 */
function checkAndCleanup(
  map: Map<any, CacheEntry>,
  metadata: CacheMetadata,
): void {
  const maxSizeBytes = CACHE_CONFIG.MAX_CACHE_SIZE_MB * 1024 * 1024;
  const thresholdBytes = maxSizeBytes * CACHE_CONFIG.CLEANUP_THRESHOLD;

  // Check if we're over the entry limit
  if (map.size > CACHE_CONFIG.MAX_ENTRIES) {
    const entriesToRemove = map.size - CACHE_CONFIG.MAX_ENTRIES;
    evictEntries(map, metadata, entriesToRemove * 10000); // Rough estimate
    return;
  }

  // Check if we're over the size threshold
  if (metadata.totalSize > thresholdBytes) {
    const targetReduction = metadata.totalSize - maxSizeBytes * 0.6; // Target 60% capacity
    evictEntries(map, metadata, targetReduction);
  }
}

/**
 * Check if data exists in localStorage cache for a given query
 * Used to determine if we should show "Fetch Data" button or auto-display cached data
 */
export function checkCacheForQuery(
  queryId: string,
  limit: number = 100,
  sortBy?: string,
  sortOrder?: string,
): boolean {
  try {
    const rawCache = localStorage.getItem("app-cache");
    if (!rawCache) return false;

    const cacheData: Array<[string, any]> = JSON.parse(rawCache);

    // SWR infinite uses $inf$ prefix and stores array of keys
    // Key format: ['/api/apegpt/data/sse', id, offset, limit, sortBy, sortOrder]
    const targetKeyStart = `$inf$@"/api/apegpt/data/sse",`;

    for (const [key, value] of cacheData) {
      if (
        typeof key === "string" &&
        key.includes(targetKeyStart) &&
        key.includes(queryId)
      ) {
        // Found a matching cache entry
        if (value && Array.isArray(value) && value.length > 0) {
          console.log("[Cache] Found cached data for query", { queryId, key });
          return true;
        }
      }
    }
    return false;
  } catch (error) {
    console.warn("[Cache] Error checking cache:", error);
    return false;
  }
}

export function localStorageProvider() {
  // Load metadata
  let metadata = loadMetadata();

  // When initializing, we restore the data from `localStorage` into a map.
  let cacheData: Array<[string, any]> = [];
  try {
    const rawCache = localStorage.getItem("app-cache");
    if (rawCache) {
      // Check if the cache is too large before parsing
      const cacheSize = new Blob([rawCache]).size;
      const maxSizeBytes = CACHE_CONFIG.MAX_CACHE_SIZE_MB * 1024 * 1024;

      if (cacheSize > maxSizeBytes * 1.5) {
        console.warn(
          `[Cache] Existing cache (${(cacheSize / 1024 / 1024).toFixed(2)} MB) is too large. Clearing for fresh start.`,
        );
        localStorage.removeItem("app-cache");
        localStorage.removeItem("app-cache-metadata");
        cacheData = [];
      } else {
        cacheData = JSON.parse(rawCache);
      }
    }
  } catch (error) {
    console.warn("[Cache] Failed to load cache data, clearing:", error);
    localStorage.removeItem("app-cache");
    localStorage.removeItem("app-cache-metadata");
  }

  // Convert stored data to CacheEntry format
  const map = new Map<any, CacheEntry>();
  for (const [key, value] of cacheData) {
    const meta = metadata.entries[key];
    const entry: CacheEntry = {
      value,
      lastAccessed: meta?.lastAccessed || Date.now(),
      size: meta?.size || estimateSize(value),
    };
    map.set(key, entry);
  }

  // Perform initial cleanup if needed
  checkAndCleanup(map, metadata);

  // Override the get method to track access time
  const originalGet = map.get;
  map.get = function (key: any): any {
    const entry = originalGet.call(this, key);
    if (entry) {
      entry.lastAccessed = Date.now();
      const normalizedKey = typeof key === "string" ? key : JSON.stringify(key);
      if (metadata.entries[normalizedKey]) {
        metadata.entries[normalizedKey].lastAccessed = entry.lastAccessed;
      }
      return entry.value;
    }
    return undefined;
  };

  // Track if there are unsaved changes
  let hasChanges = false;

  // Override the set method to track size and handle quota
  const originalSet = map.set;
  map.set = function (key: any, value: any) {
    const normalizedKey = typeof key === "string" ? key : JSON.stringify(key);
    const size = estimateSize(value);
    const now = Date.now();

    const entry: CacheEntry = {
      value,
      lastAccessed: now,
      size,
    };

    // Update metadata
    const existingEntry = originalGet.call(map, key);
    if (existingEntry) {
      metadata.totalSize -= existingEntry.size;
    }
    metadata.totalSize += size;
    metadata.entries[normalizedKey] = {
      lastAccessed: now,
      size,
    };

    // Check if we need cleanup before setting
    checkAndCleanup(map, metadata);

    hasChanges = true;
    return originalSet.call(this, key, entry);
  };

  // Override the delete method to update metadata
  const originalDelete = map.delete;
  map.delete = function (key: any): boolean {
    const normalizedKey = typeof key === "string" ? key : JSON.stringify(key);
    const entry = map.get(key);
    if (entry) {
      metadata.totalSize = Math.max(0, metadata.totalSize - entry.size);
      delete metadata.entries[normalizedKey];
    }
    return originalDelete.call(this, key);
  };

  // Save to localStorage with error handling
  const saveToLocalStorage = () => {
    try {
      // Convert map to storable format
      const entries = Array.from(map.entries()).map(([key, entry]) => [
        key,
        entry.value,
      ]);
      const appCache = JSON.stringify(entries);

      // Check if we're likely to exceed quota
      const estimatedSize = new Blob([appCache]).size;
      const maxSizeBytes = CACHE_CONFIG.MAX_CACHE_SIZE_MB * 1024 * 1024;

      if (estimatedSize > maxSizeBytes) {
        console.warn(
          `[Cache] Cache size (${(estimatedSize / 1024 / 1024).toFixed(2)} MB) exceeds limit. Performing emergency cleanup.`,
        );
        evictEntries(map, metadata, estimatedSize - maxSizeBytes * 0.5);
        // Retry with cleaned cache
        const cleanedEntries = Array.from(map.entries()).map(([key, entry]) => [
          key,
          entry.value,
        ]);
        localStorage.setItem("app-cache", JSON.stringify(cleanedEntries));
      } else {
        localStorage.setItem("app-cache", appCache);
      }

      saveMetadata(metadata);
    } catch (error: any) {
      if (error.name === "QuotaExceededError") {
        console.error("[Cache] localStorage quota exceeded. Clearing cache.");
        // Emergency: clear the cache
        localStorage.removeItem("app-cache");
        localStorage.removeItem("app-cache-metadata");
        map.clear();
        metadata = { entries: {}, totalSize: 0 };
      } else {
        console.error("[Cache] Failed to save cache:", error);
      }
    }
  };

  // Before unloading the app, we write back all the data into `localStorage`.
  const beforeUnloadHandler = () => {
    saveToLocalStorage();
    clearInterval(periodicSave);
  };
  window.addEventListener("beforeunload", beforeUnloadHandler);

  // Periodic save (every 60 seconds if there are changes)
  const periodicSave = setInterval(() => {
    if (hasChanges) {
      saveToLocalStorage();
      hasChanges = false;
    }
  }, 60000); // Increased to 60 seconds to reduce save frequency

  // We still use the map for write & read for performance.
  return map as any;
}
