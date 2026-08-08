import { validatePassword } from "./validate";
import { createJWT } from "../user/tokens";

export function login(username: string, password: string): string {
  validatePassword(password);
  return createJWT(username);
}

export async function loginAsync(username: string, password: string): Promise<string> {
  return login(username, password);
}
