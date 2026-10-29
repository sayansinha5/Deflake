import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { ToastProvider, useToast } from "./components/ui/Toast";
import { AuthProvider } from "./hooks/useAuth";
import { AppRoutes } from "./routes";

function ToastFromLocation() {
  const location = useLocation();
  const navigate = useNavigate();
  const { push } = useToast();

  useEffect(() => {
    const message = location.state?.toast;
    if (!message) return;
    push({ message });
    navigate(`${location.pathname}${location.search}`, { replace: true, state: null });
  }, [location, navigate, push]);

  return null;
}

export function App() {
  return (
    <ToastProvider>
      <AuthProvider>
        <ToastFromLocation />
        <AppRoutes />
      </AuthProvider>
    </ToastProvider>
  );
}
