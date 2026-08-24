import { Suspense, lazy } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import AppShell from './components/AppShell';
import { ToastProvider } from './components/Toast';
import { Skeleton } from './components/ui';
import UploadPage from './pages/UploadPage';

// Route-level code splitting. The single bundle had grown past 700 kB, most
// of it ECharts, which every visitor paid for on first load even though the
// landing route (upload) doesn't chart anything until a file arrives.
// UploadPage stays eagerly imported because it IS the landing route — lazy
// loading it would add a round-trip to the first paint.
const MetadataConfirmPage = lazy(() => import('./pages/MetadataConfirmPage'));
const SpectrumViewPage = lazy(() => import('./pages/SpectrumViewPage'));
const ComparePage = lazy(() => import('./pages/ComparePage'));
const RoutinesPage = lazy(() => import('./pages/RoutinesPage'));
const SearchPage = lazy(() => import('./pages/SearchPage'));
const LibraryPage = lazy(() => import('./pages/LibraryPage'));
const TrendingPage = lazy(() => import('./pages/TrendingPage'));
const FeedPage = lazy(() => import('./pages/FeedPage'));
const FindingPage = lazy(() => import('./pages/FindingPage'));
const FindingComposerPage = lazy(() => import('./pages/FindingComposerPage'));
const ProfilePage = lazy(() => import('./pages/ProfilePage'));
const LoginPage = lazy(() => import('./pages/LoginPage'));
const TermsPage = lazy(() => import('./pages/TermsPage'));
const PrivacyPage = lazy(() => import('./pages/PrivacyPage'));

export default function App() {
  return (
    <BrowserRouter>
      <ToastProvider>
        <AppShell>
          <Suspense fallback={<Skeleton lines={5} height="2rem" />}>
            <Routes>
              {/* "/" drops the user straight into the toolbox (upload), per the
                  architecture doc's landing-experience requirement. */}
              <Route path="/" element={<Navigate to="/upload" replace />} />
              <Route path="/login" element={<LoginPage />} />
              <Route path="/upload" element={<UploadPage />} />
              <Route path="/ingestion/:jobId/confirm" element={<MetadataConfirmPage />} />
              <Route path="/spectra/:id" element={<SpectrumViewPage />} />
              {/* Accession permalink — the form that survives in a printed
                  citation. Resolved by the same page. */}
              <Route path="/s/:accession" element={<SpectrumViewPage />} />
              <Route path="/compare" element={<ComparePage />} />
              <Route path="/routines" element={<RoutinesPage />} />
              <Route path="/search" element={<SearchPage />} />
              <Route path="/library" element={<LibraryPage />} />
              <Route path="/trending" element={<TrendingPage />} />
              <Route path="/feed" element={<FeedPage />} />
              <Route path="/findings/new" element={<FindingComposerPage />} />
              <Route path="/findings/:id/edit" element={<FindingComposerPage />} />
              <Route path="/findings/:id" element={<FindingPage />} />
              <Route path="/u/:handle" element={<ProfilePage />} />
              <Route path="/terms" element={<TermsPage />} />
              <Route path="/privacy" element={<PrivacyPage />} />
            </Routes>
          </Suspense>
        </AppShell>
      </ToastProvider>
    </BrowserRouter>
  );
}
