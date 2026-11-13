import type { components } from "./schema";
import { client } from "./session";

export type PersonalContext = components["schemas"]["ContextOut"];

export const fetchContext = () => client.get("/context") as Promise<PersonalContext>;
export const saveContext = (text: string) =>
  client.send("PUT", "/context", { text }) as Promise<PersonalContext>;
