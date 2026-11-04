import { createClient } from "./client";
import type { components } from "./schema";

export type Me = components["schemas"]["Me"];
export type Credentials = components["schemas"]["Credentials"];

// A full page load, not a router navigation: it also discards every piece of
// the user's data held in memory.
export const client = createClient(() => {
  window.location.assign("/login");
});

export const fetchMe = () => client.get("/auth/me") as Promise<Me>;
export const logIn = (credentials: Credentials) => client.send("POST", "/auth/login", credentials);
export const register = (credentials: Credentials) =>
  client.send("POST", "/auth/register", credentials);
export const logOut = () => client.send("POST", "/auth/logout");
