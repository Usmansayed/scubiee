export function validatePassword(password: string): void {
  if (!password || password.length < 8) {
    throw new Error("invalid password");
  }
}

export function validateUsername(username: string): boolean {
  return /^[a-zA-Z0-9_]+$/.test(username);
}
