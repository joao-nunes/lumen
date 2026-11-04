import { useQuery, useQueryClient } from "@tanstack/react-query";
import { NavLink, Outlet, useNavigate } from "react-router";
import { fetchMe, logOut } from "../api/session";
import styles from "./AuthenticatedLayout.module.css";

/** Every screen behind login. A missing session sends the user to Log in (see api/session.ts). */
export function AuthenticatedLayout() {
  const me = useQuery({ queryKey: ["me"], queryFn: fetchMe });
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  if (me.isPending) {
    return <p>Loading…</p>;
  }
  if (me.isError) {
    return <p role="alert">Lumen couldn't be reached. Reload the page to try again.</p>;
  }

  async function handleLogOut() {
    await logOut();
    queryClient.clear(); // the next user of this browser must not see this user's cached data
    await navigate("/login");
  }

  return (
    <>
      <header className={styles.header}>
        <nav className={styles.nav}>
          <NavLink to="/">Today</NavLink>
          <NavLink to="/overview">Overview</NavLink>
        </nav>
        <span className={styles.account}>
          {me.data.email}
          <button type="button" onClick={() => void handleLogOut()}>
            Log out
          </button>
        </span>
      </header>
      <main>
        <Outlet />
      </main>
    </>
  );
}
