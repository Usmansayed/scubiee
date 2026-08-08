export function createJWT(subject: string): string {
  return `jwt:${subject}`;
}

export function decodeJWT(token: string): string {
  return token.replace(/^jwt:/, "");
}
