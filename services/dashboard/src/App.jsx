import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './auth/AuthContext';
import { StreamProvider } from './stream/StreamContext';
import { ProtectedRoute } from './components/ProtectedRoute';
import { Layout } from './components/Layout';
import { Login } from './screens/Login';
import { Ticker } from './screens/Ticker';
import { Positions } from './screens/Positions';
import { Trades } from './screens/Trades';
import { Risk } from './screens/Risk';
import { Audit } from './screens/Audit';

export default function App() {
  return (
    <AuthProvider>
      <StreamProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route
              element={
                <ProtectedRoute>
                  <Layout />
                </ProtectedRoute>
              }
            >
              <Route path="/" element={<Ticker />} />
              <Route path="/positions" element={<Positions />} />
              <Route path="/trades" element={<Trades />} />
              <Route path="/risk" element={<Risk />} />
              <Route path="/audit" element={<Audit />} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </StreamProvider>
    </AuthProvider>
  );
}
