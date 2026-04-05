import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';

// Create a context for the media cache
const MediaCacheContext = createContext();

// Maximum number of shorts to keep in cache
const MAX_CACHED_ITEMS = 15;
// Max blob URLs to keep (memory management)
const MAX_BLOB_URLS = 20;
// Number of most recent shorts to keep in memory
export const RECENT_SHORTS_WINDOW = 10;

export function MediaCacheProvider({ children }) {
  // OPTIMIZED: Use ref for internal state that doesn't need renders
  const mediaCacheRef = useRef(new Map());
  // For component re-renders when we need them
  const [cacheSize, setCacheSize] = useState(0);
  // Track active fetch operations to prevent duplicates
  const activeFetches = useRef(new Map());
  // Track blob URLs for cleanup
  const blobUrls = useRef([]);
  // Track recently viewed shorts for sliding window
  const recentlyViewedShorts = useRef([]);
  // Performance tracking
  const perfMetrics = useRef({
    cacheHits: 0,
    cacheMisses: 0,
    blobsCreated: 0,
    itemsEvicted: 0,
    manualEvictions: 0
  });

  // Debug logging - throttled to avoid spamming
  const lastLogTime = useRef(0);
  useEffect(() => {
    const now = Date.now();
    if (now - lastLogTime.current > 5000) {
      console.log(`📱 Media Cache: ${mediaCacheRef.current.size} items cached`);
      console.log(`Performance: ${JSON.stringify(perfMetrics.current)}`);
      lastLogTime.current = now;
    }
  }, [cacheSize]);

  // Clean up blob URLs when component unmounts
  useEffect(() => {
    return () => {
      blobUrls.current.forEach(url => {
        try {
          URL.revokeObjectURL(url);
        } catch (e) {
          console.warn('Failed to revoke blob URL', e);
        }
      });
    };
  }, []);

  // OPTIMIZED: Mark a short as viewed with batched updates
  const markShortAsViewed = useCallback((shortId) => {
    if (!shortId) return;
    
    const isAlreadyMostRecent = 
      recentlyViewedShorts.current.length > 0 && 
      recentlyViewedShorts.current[0] === shortId;
    
    if (isAlreadyMostRecent) return;
    
    // Remove if already exists (to move to front)
    recentlyViewedShorts.current = recentlyViewedShorts.current.filter(id => id !== shortId);
    
    // Add to front of array (most recently viewed)
    recentlyViewedShorts.current.unshift(shortId);
    
    // Maintain sliding window size
    if (recentlyViewedShorts.current.length > RECENT_SHORTS_WINDOW) {
      const shortsToEvict = recentlyViewedShorts.current.slice(RECENT_SHORTS_WINDOW);
      recentlyViewedShorts.current = recentlyViewedShorts.current.slice(0, RECENT_SHORTS_WINDOW);
      
      // Schedule eviction in next tick to avoid blocking the current operation
      setTimeout(() => {
        unloadShortsMedia(shortsToEvict);
      }, 0);
    }
  }, []);

  // OPTIMIZED: Unload media with reduced re-renders
  const unloadShortsMedia = useCallback((shortIds) => {
    if (!shortIds || shortIds.length === 0) return;
    
    console.log(`🧹 Unloading media for ${shortIds.length} shorts outside viewing window`);
    
    let evictionCount = 0;
    
    shortIds.forEach(shortId => {
      if (mediaCacheRef.current.has(shortId)) {
        // Get cached item
        const cachedItem = mediaCacheRef.current.get(shortId);
        
        // Revoke any blob URLs
        if (cachedItem && cachedItem.mediaItems) {
          cachedItem.mediaItems.forEach(item => {
            if (item.blobUrl && item.type !== 'video' && blobUrls.current.includes(item.blobUrl)) {
              try {
                URL.revokeObjectURL(item.blobUrl);
                // Remove from blob URLs array
                const idx = blobUrls.current.indexOf(item.blobUrl);
                if (idx !== -1) {
                  blobUrls.current.splice(idx, 1);
                }
              } catch (e) {
                console.warn(`Failed to revoke blob URL for ${shortId}`, e);
              }
            }
          });
        }
        
        // Remove from cache
        mediaCacheRef.current.delete(shortId);
        evictionCount++;
      }
    });
    
    if (evictionCount > 0) {
      perfMetrics.current.manualEvictions += evictionCount;
      console.log(`✅ Evicted ${evictionCount} shorts from cache`);
      setCacheSize(mediaCacheRef.current.size);
    }
  }, []);

  // OPTIMIZED: Create blob URL with better error handling and timeouts
  const createBlobUrl = useCallback(async (url, type) => {
    try {
      // Skip if we're in the middle of fetching this URL
      if (activeFetches.current.has(url)) {
        return activeFetches.current.get(url);
      }

      // Create a promise for this fetch operation
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 10000); // 10-second timeout
      
      const fetchPromise = fetch(url, { signal: controller.signal })
        .then(response => {
          if (!response.ok) throw new Error(`Error fetching ${url}: ${response.status}`);
          return response.blob();
        })
        .then(blob => {
          clearTimeout(timeoutId);
          const blobUrl = URL.createObjectURL(blob);
          
          // Keep track of blob URLs for cleanup
          blobUrls.current.push(blobUrl);
          perfMetrics.current.blobsCreated++;
          
          // Clean up old blob URLs if we exceed our limit
          if (blobUrls.current.length > MAX_BLOB_URLS) {
            const urlToRevoke = blobUrls.current.shift();
            try {
              URL.revokeObjectURL(urlToRevoke);
            } catch (e) {
              console.warn('Failed to revoke blob URL', e);
            }
          }
          
          // Remove from active fetches
          activeFetches.current.delete(url);
          
          return blobUrl;
        })
        .catch(error => {
          clearTimeout(timeoutId);
          console.error(`Error creating blob URL for ${url}`, error);
          activeFetches.current.delete(url);
          // Return original URL as fallback
          return url;
        });

      // Store the promise in active fetches
      activeFetches.current.set(url, fetchPromise);
      return fetchPromise;
    } catch (error) {
      console.error(`Error in createBlobUrl for ${url}`, error);
      return url; // Fallback to original URL
    }
  }, []);

  // OPTIMIZED: Preload media with batched updates and better error handling
  const preloadMedia = useCallback(async (shortId, mediaItems) => {
    try {
      // Skip if already in cache
      if (mediaCacheRef.current.has(shortId)) {
        perfMetrics.current.cacheHits++;
        return mediaCacheRef.current.get(shortId).mediaItems;
      }

      perfMetrics.current.cacheMisses++;
      
      // Create placeholder entries with the original URLs
      const initialItems = mediaItems.map(item => ({
        ...item,
        blobUrl: null,
        loaded: false,
        originalUrl: item.cachedUrl || item.url
      }));
      
      // Apply LRU eviction if needed but preserve recently viewed shorts
      if (mediaCacheRef.current.size >= MAX_CACHED_ITEMS) {
        // Get set of recent shorts for lookup
        const recentShortIds = new Set(recentlyViewedShorts.current);
        
        // Find candidates for eviction (not in recently viewed list)
        const candidatesForEviction = Array.from(mediaCacheRef.current.keys())
          .filter(key => !recentShortIds.has(key));
        
        if (candidatesForEviction.length > 0) {
          // Evict the first non-recent short
          const shortToEvict = candidatesForEviction[0];
          mediaCacheRef.current.delete(shortToEvict);
          perfMetrics.current.itemsEvicted++;
        } else {
          // If all shorts are recent, use standard LRU
          const oldestKey = mediaCacheRef.current.keys().next().value;
          mediaCacheRef.current.delete(oldestKey);
          perfMetrics.current.itemsEvicted++;
        }
      }
      
      // Add to cache immediately with placeholders
      mediaCacheRef.current.set(shortId, {
        mediaItems: initialItems,
        timestamp: Date.now()
      });
      
      // Update UI without re-rendering all children
      setCacheSize(mediaCacheRef.current.size);
      
      // Process media items in chunks to avoid overwhelming the browser
      const processMediaItems = async () => {
        const results = [];
        
        // Process in smaller batches
        for (let i = 0; i < initialItems.length; i++) {
          const item = initialItems[i];
          try {
            const mediaUrl = item.originalUrl;
            if (!mediaUrl) {
              results.push({ index: i, blobUrl: null, loaded: false });
              continue;
            }
            
            // Only create blob URLs for images - videos use src directly
            if (item.type !== 'video') {
              const blobUrl = await createBlobUrl(mediaUrl, item.type);
              results.push({ index: i, blobUrl, loaded: true });
            } else {
              // For videos, just mark as loaded but use original URL
              results.push({ index: i, blobUrl: mediaUrl, loaded: true });
            }
            
            // Update the cache as we go to make items available immediately
            if (mediaCacheRef.current.has(shortId)) {
              const cachedItems = mediaCacheRef.current.get(shortId);
              const newItems = [...cachedItems.mediaItems];
              newItems[i] = {
                ...newItems[i],
                blobUrl: results[results.length - 1].blobUrl,
                loaded: results[results.length - 1].loaded
              };
              
              mediaCacheRef.current.set(shortId, {
                ...cachedItems,
                mediaItems: newItems,
                timestamp: Date.now()
              });
            }
          } catch (e) {
            console.error(`Failed to preload media item ${i}`, e);
            results.push({ index: i, blobUrl: null, loaded: false });
          }
        }
        
        return results;
      };
      
      // Process media items and update cache after all are done
      processMediaItems();
      
      return initialItems;
    } catch (error) {
      console.error(`Error preloading media for short ${shortId}`, error);
      return mediaItems;
    }
  }, [createBlobUrl]);

  // OPTIMIZED: Get cached media with reduced side effects
  const getCachedMedia = useCallback((shortId) => {
    if (!mediaCacheRef.current.has(shortId)) return null;
    
    // Mark as recently viewed without triggering a state update
    markShortAsViewed(shortId);
    
    // Get the cached items
    const cachedItems = mediaCacheRef.current.get(shortId);
    
    // No re-render needed here
    mediaCacheRef.current.set(shortId, {
      ...cachedItems,
      timestamp: Date.now()
    });
    
    perfMetrics.current.cacheHits++;
    return cachedItems.mediaItems;
  }, [markShortAsViewed]);

  // Check if media is cached
  const isMediaCached = useCallback((shortId) => {
    return mediaCacheRef.current.has(shortId);
  }, []);

  // Get list of recently viewed shorts for prefetching decisions
  const getRecentlyViewedShorts = useCallback(() => {
    return [...recentlyViewedShorts.current];
  }, []);

  // Clear the entire cache
  const clearCache = useCallback(() => {
    // Revoke all blob URLs
    blobUrls.current.forEach(url => {
      try {
        URL.revokeObjectURL(url);
      } catch (e) {
        console.warn('Failed to revoke blob URL', e);
      }
    });
    
    blobUrls.current = [];
    recentlyViewedShorts.current = [];
    mediaCacheRef.current.clear();
    setCacheSize(0);
    
    console.log('🧹 Media cache cleared');
  }, []);

  // Get metrics for debugging
  const getMetrics = useCallback(() => {
    return {
      ...perfMetrics.current,
      cacheSize: mediaCacheRef.current.size,
      blobUrlsCount: blobUrls.current.length,
      activeFetches: activeFetches.current.size,
      recentShortsCount: recentlyViewedShorts.current.length,
      recentShorts: recentlyViewedShorts.current
    };
  }, []);

  // Create value object only when dependencies change
  const contextValue = React.useMemo(() => ({
    preloadMedia,
    getCachedMedia,
    isMediaCached,
    markShortAsViewed,
    unloadShortsMedia,
    getRecentlyViewedShorts,
    clearCache,
    getMetrics,
    cacheSize
  }), [
    preloadMedia,
    getCachedMedia,
    isMediaCached,
    markShortAsViewed,
    unloadShortsMedia,
    getRecentlyViewedShorts,
    clearCache,
    getMetrics,
    cacheSize
  ]);

  return (
    <MediaCacheContext.Provider value={contextValue}>
      {children}
    </MediaCacheContext.Provider>
  );
}

// Custom hook to use the media cache
export function useMediaCache() {
  const context = useContext(MediaCacheContext);
  if (!context) {
    throw new Error('useMediaCache must be used within a MediaCacheProvider');
  }
  return context;
}
