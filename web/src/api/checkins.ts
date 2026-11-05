import type { components } from "./schema";
import { client } from "./session";

export type Day = components["schemas"]["DayOut"];
export type CheckinIn = components["schemas"]["CheckinIn"];
export type DimensionInfo = components["schemas"]["DimensionOut"];
export type TagUsage = components["schemas"]["TagOut"];

export const fetchDimensions = () => client.get("/dimensions") as Promise<DimensionInfo[]>;
export const fetchTags = () => client.get("/tags") as Promise<TagUsage[]>;
export const fetchDay = (date: string) => client.get(`/checkins/${date}`) as Promise<Day>;
export const saveDay = (date: string, checkin: CheckinIn) =>
  client.send("PUT", `/checkins/${date}`, checkin) as Promise<Day>;
