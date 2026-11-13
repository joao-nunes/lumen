import { Route, Routes } from "react-router";
import styles from "./App.module.css";
import { AuthenticatedLayout } from "./screens/AuthenticatedLayout";
import { AuthForm } from "./screens/AuthForm";
import { OverviewScreen } from "./screens/OverviewScreen";
import { ThemeToggle } from "./screens/ThemeToggle";
import { TodayScreen } from "./screens/TodayScreen";

export function App() {
  return (
    <div className={styles.page}>
      <div className={styles.content}>
        <Routes>
          <Route path="/login" element={<AuthForm mode="login" />} />
          <Route path="/register" element={<AuthForm mode="register" />} />
          <Route element={<AuthenticatedLayout />}>
            <Route path="/" element={<TodayScreen />} />
            <Route path="/overview" element={<OverviewScreen />} />
          </Route>
        </Routes>
      </div>
      <footer className={styles.footer}>
        <p>
          Lumen is not a crisis service. If you are in danger, contact your local emergency number.
        </p>
        <ThemeToggle />
      </footer>
    </div>
  );
}
