import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router";
import { errorMessage } from "../api/client";
import { fetchMe, logOut } from "../api/session";
import styles from "./AuthenticatedLayout.module.css";

/** Every screen behind login. A missing session sends the user to Log in (see api/session.ts). */
export function AuthenticatedLayout() {
  const me = useQuery({ queryKey: ["me"], queryFn: fetchMe });
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [logOutError, setLogOutError] = useState<string | null>(null);

  if (me.isPending) {
    return <p>Loading…</p>;
  }
  if (me.isError) {
    return <p role="alert">Lumen couldn't be reached. Reload the page to try again.</p>;
  }

  async function handleLogOut() {
    try {
      await logOut();
    } catch (error) {
      setLogOutError(errorMessage(error));
      return;
    }
    queryClient.clear(); // the next user of this browser must not see this user's cached data
    await navigate("/login");
  }

  return (
    <>
      <header className={styles.header}>
        <nav className={styles.nav}>
          <NavLink to="/">Today</NavLink>
          <NavLink to="/overview">Overview</NavLink>
          <NavLink to="/context">Personal context</NavLink>
        </nav>
        <span className={styles.account}>
          {me.data.email}
          <button type="button" onClick={() => void handleLogOut()}>
            Log out
          </button>
        </span>
      </header>
      {logOutError !== null && <p role="alert">{logOutError}</p>}
      <main>
        <Outlet />
      </main>
    </>
  );
}
