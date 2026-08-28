import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import AppShell from './components/AppShell';
import LoginPage from './pages/LoginPage';
import UploadPage from './pages/UploadPage';
import MetadataConfirmPage from './pages/MetadataConfirmPage';
import SpectrumViewPage from './pages/SpectrumViewPage';
import RoutinesPage from './pages/RoutinesPage';
import SearchPage from './pages/SearchPage';
import LibraryPage from './pages/LibraryPage';
import TrendingPage from './pages/TrendingPage';
import CommonsPage from './pages/CommonsPage';
import PublicRecordPage from './pages/PublicRecordPage';
import PublicProfilePage from './pages/PublicProfilePage';
import PostPage from './pages/PostPage';
import CreatePostPage from './pages/CreatePostPage';
import NotificationsPage from './pages/NotificationsPage';
import AccountPage from './pages/AccountPage';
import AnalysisPage from './pages/AnalysisPage';
import TermsPage from './pages/TermsPage';
import PrivacyPage from './pages/PrivacyPage';

export default function App() {
  return (
    <BrowserRouter>
      <AppShell>
        <Routes>
          {/* "/" drops the user straight into the toolbox (upload), per the
              architecture doc's landing-experience requirement. */}
          <Route path="/" element={<Navigate to="/upload" replace />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/upload" element={<UploadPage />} />
          <Route path="/ingestion/:jobId/confirm" element={<MetadataConfirmPage />} />
          <Route path="/spectra/:id" element={<SpectrumViewPage />} />
          <Route path="/routines" element={<RoutinesPage />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/library" element={<LibraryPage />} />
          <Route path="/trending" element={<TrendingPage />} />
          <Route path="/commons" element={<CommonsPage />} />
          <Route path="/public/spectra/:id" element={<PublicRecordPage />} />
          <Route path="/profiles/:handle" element={<PublicProfilePage />} />
          <Route path="/community/posts/:id" element={<PostPage />} />
          <Route path="/community/new" element={<CreatePostPage />} />
          <Route path="/notifications" element={<NotificationsPage />} />
          <Route path="/account" element={<AccountPage />} />
          <Route path="/analysis" element={<AnalysisPage />} />
          <Route path="/terms" element={<TermsPage />} />
          <Route path="/privacy" element={<PrivacyPage />} />
        </Routes>
      </AppShell>
    </BrowserRouter>
  );
}
