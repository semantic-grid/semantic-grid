/**
 * V2 Notebook Landing Page
 *
 * Creates a new session and redirects to the notebook interface.
 */

'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Box, CircularProgress, Typography, Alert } from '@mui/material';
import { useUser } from '@auth0/nextjs-auth0/client';
import { createV2Session, getV2AuthToken } from '@/app/lib/v2';

export default function NotebookLandingPage() {
  const router = useRouter();
  const { user } = useUser();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const createSession = async () => {
      try {
        // Get auth token (guest or user)
        const token = await getV2AuthToken(user);

        // Create new v2 session
        const session = await createV2Session(
          {
            name: `Notebook ${new Date().toLocaleDateString()}`,
            description: 'V2 Notebook Session',
          },
          token
        );

        // Redirect to notebook page
        router.push(`/nb/${session.session_id}`);
      } catch (err) {
        console.error('Failed to create session:', err);
        setError(err instanceof Error ? err.message : 'Failed to create session');
      }
    };

    createSession();
  }, [user, router]);

  if (error) {
    return (
      <Box sx={{ p: 3 }}>
        <Alert severity="error">
          <Typography variant="h6">Failed to create session</Typography>
          <Typography variant="body2">{error}</Typography>
        </Alert>
      </Box>
    );
  }

  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: '100vh',
        gap: 2,
      }}
    >
      <CircularProgress size={60} />
      <Typography variant="h6">Creating your notebook...</Typography>
    </Box>
  );
}
