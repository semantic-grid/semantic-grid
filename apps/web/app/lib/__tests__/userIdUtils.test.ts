import { auth0SubToUuid } from '../userIdUtils';

describe('userIdUtils', () => {
  describe('auth0SubToUuid', () => {
    it('should convert Auth0 ID to UUID v5 deterministically', () => {
      const auth0Id = 'google-oauth2|105966005238951737850';
      const uuid1 = auth0SubToUuid(auth0Id);
      const uuid2 = auth0SubToUuid(auth0Id);
      
      // Should be deterministic (same input = same output)
      expect(uuid1).toBe(uuid2);
      
      // Should be valid UUID format
      expect(uuid1).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
      
      // Should be version 5
      expect(uuid1.charAt(14)).toBe('5');
      
      console.log('Auth0 ID:', auth0Id);
      console.log('UUID v5: ', uuid1);
    });
    
    it('should produce different UUIDs for different Auth0 IDs', () => {
      const uuid1 = auth0SubToUuid('google-oauth2|105966005238951737850');
      const uuid2 = auth0SubToUuid('auth0|123456789');
      
      expect(uuid1).not.toBe(uuid2);
    });
  });
});
