import type { components } from "./schema";
import { client } from "./session";

export type Overview = components["schemas"]["OverviewOut"];
export type DimensionOverview = components["schemas"]["DimensionOverviewOut"];

export const fetchOverview = (end: string) =>
  client.get(`/overview?end=${end}`) as Promise<Overview>;
