import { createHash } from 'crypto';

/**
 * Custom namespace UUID for Semantic Grid Auth0 user conversions
 * This is a fixed UUID that serves as the namespace for all Auth0 ID conversions
 */
const SEMANTIC_GRID_AUTH0_NAMESPACE = '6ba7b810-9dad-11d1-80b4-00c04fd430c8';

/**
 * Converts an Auth0 user ID (e.g., "google-oauth2|105966005238951737850") 
 * to a deterministic UUID v5 format.
 * 
 * This ensures:
 * - Consistent UUID format for all users (guest and authenticated)
 * - URL-safe IDs without special characters
 * - Deterministic conversion (same input always produces same UUID)
 * - Collision-resistant
 * 
 * @param auth0Sub - The Auth0 user ID (from session.user.sub)
 * @returns A UUID v5 string in format: xxxxxxxx-xxxx-5xxx-xxxx-xxxxxxxxxxxx
 * 
 * @example
 * ```typescript
 * const uuid = auth0SubToUuid('google-oauth2|105966005238951737850');
 * // Returns: "7a3f8d2e-4b1c-5e9a-8f2d-3c4e5a6b7c8d"
 * ```
 */
export function auth0SubToUuid(auth0Sub: string): string {
  // Create SHA-1 hash of namespace + auth0 ID (UUID v5 spec)
  const hash = createHash('sha1')
    .update(SEMANTIC_GRID_AUTH0_NAMESPACE + auth0Sub)
    .digest('hex');
  
  // Format as UUID v5: xxxxxxxx-xxxx-5xxx-yxxx-xxxxxxxxxxxx
  // Where:
  // - x = any hex digit
  // - 5 = version (UUID v5)
  // - y = variant bits (10xx in binary, 8-b in hex)
  
  const uuid = [
    hash.substring(0, 8),                                           // 8 chars
    hash.substring(8, 12),                                          // 4 chars
    `5${  hash.substring(13, 16)}`,                                   // 4 chars (version 5)
    ((parseInt(hash.substring(16, 18), 16) & 0x3f) | 0x80)        // 2 chars (variant bits)
      .toString(16)
      .padStart(2, '0') + hash.substring(18, 20),                  // + 2 chars = 4 chars
    hash.substring(20, 32)                                          // 12 chars
  ].join('-');
  
  return uuid;
}

/**
 * Determines if a user ID is from Auth0 (vs guest JWT)
 * 
 * @param userId - The user ID to check
 * @returns true if it's an Auth0 ID (contains | or common provider prefixes)
 */
export function isAuth0UserId(userId: string): boolean {
  // Auth0 IDs contain pipe character or start with common provider prefixes
  return userId.includes('|') || 
         userId.startsWith('auth0') || 
         userId.startsWith('google-oauth2') ||
         userId.startsWith('github') ||
         userId.startsWith('twitter') ||
         userId.startsWith('facebook');
}

/**
 * Determines if a user ID is a guest JWT
 * 
 * @param userId - The user ID to check
 * @returns true if it's a JWT (starts with "ey" and contains dots)
 */
export function isGuestJwt(userId: string): boolean {
  return userId.startsWith('ey') && userId.includes('.');
}

/**
 * Normalizes any user ID (Auth0 or guest) to a consistent format
 * - Auth0 IDs are converted to UUID v5
 * - Guest UUIDs are passed through as-is
 * - Guest JWTs need to be decoded first (not handled here)
 * 
 * @param userId - The user ID to normalize
 * @returns A normalized UUID string
 */
export function normalizeUserId(userId: string): string {
  if (isAuth0UserId(userId)) {
    return auth0SubToUuid(userId);
  }
  return userId; // Already a UUID (guest)
}
