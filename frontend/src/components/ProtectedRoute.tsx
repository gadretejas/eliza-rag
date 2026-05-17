import type { ReactNode } from "react";
import { useAuth } from "../contexts/AuthContext";
import LoginPage from "../pages/LoginPage";

interface Props {
  children: ReactNode;
}

/**
 * Renders children if the user is authenticated; otherwise shows the login page.
 * Token expiry is checked client-side via the decoded JWT exp claim.
 */
export default function ProtectedRoute({ children }: Props) {
  const { user } = useAuth();
  if (!user) return <LoginPage />;
  return <>{children}</>;
}
