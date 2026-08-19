import { BrowserRouter, Routes, Route, Link, Navigate } from 'react-router-dom';
import LoginPage from './pages/LoginPage';
import UploadPage from './pages/UploadPage';
import MetadataConfirmPage from './pages/MetadataConfirmPage';
import SpectrumViewPage from './pages/SpectrumViewPage';
import RoutinesPage from './pages/RoutinesPage';
import SearchPage from './pages/SearchPage';
import LibraryPage from './pages/LibraryPage';
import TrendingPage from './pages/TrendingPage';

export default function App() {
  return (
    <BrowserRouter>
      <nav>
        <Link to="/upload">Upload</Link>
        <Link to="/search">Search</Link>
        <Link to="/library">My library</Link>
        <Link to="/trending">Trending</Link>
        <Link to="/routines">Routines</Link>
        <Link to="/login">Login</Link>
      </nav>
      <hr />
      <Routes>
        <Route path="/" element={<Navigate to="/upload" replace />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/upload" element={<UploadPage />} />
        <Route path="/ingestion/:jobId/confirm" element={<MetadataConfirmPage />} />
        <Route path="/spectra/:id" element={<SpectrumViewPage />} />
        <Route path="/routines" element={<RoutinesPage />} />
        <Route path="/search" element={<SearchPage />} />
        <Route path="/library" element={<LibraryPage />} />
        <Route path="/trending" element={<TrendingPage />} />
      </Routes>
    </BrowserRouter>
  );
}
