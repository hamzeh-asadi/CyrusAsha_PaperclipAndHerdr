// Internal diagnostic for the pinned embedded DB, not a general SQL client.
// The Windows caller checks the lock, process and listener before invoking it.
import { stat } from "node:fs/promises";
import { isAbsolute, resolve } from "node:path";

async function compareDirectory(actual, expected) {
  if (typeof actual !== "string" || !isAbsolute(actual)) return "sql-unavailable";
  if (resolve(actual) === resolve(expected)) return "server-dir-matches"; // pinned server's comparison
  // Report an alias only when both existing directories have the same file ID.
  // This is diagnostic, never a reason to bypass Paperclip's ownership check.
  if (process.platform === "win32" && ![actual, expected].every((p) => /^[a-z]:[\\/]/i.test(p)))
    return "dir-identity-unverified"; // do not follow server-supplied UNC/device paths
  try {
    const [a, b] = await Promise.all([actual, expected].map((p) => stat(p, { bigint: true })));
    if (a.isDirectory() && b.isDirectory() && a.ino !== 0n && b.ino !== 0n) {
      return a.dev === b.dev && a.ino === b.ino ? "same-dir-different-spelling" : "server-dir-differs";
    }
  } catch {
    // No stat permission or usable file ID is not evidence for either conclusion.
  }
  return "dir-identity-unverified";
}

async function inspect(port, dataDir, lockDir) {
  if (!Number.isInteger(port) || port < 1 || port > 65535 || !dataDir || !isAbsolute(dataDir))
    return "probe-unavailable";
  if (!lockDir || !isAbsolute(lockDir) || resolve(lockDir) !== resolve(dataDir))
    return "pid-file-dir-differs";
  let sql;
  try {
    const { default: postgres } = await import("postgres"); // already installed with Paperclip
    // Same loopback host, maintenance DB and fixed embedded role as the pinned server.
    // Never accept a connection string from config/.env or print driver exceptions.
    sql = postgres({
      host: "127.0.0.1",
      port,
      database: "postgres",
      user: "paperclip",
      password: "paperclip",
      max: 1,
      connect_timeout: 3,
      prepare: false,
      fetch_types: false,
      debug: false,
      onnotice() {},
      connection: {
        application_name: "desk_directory_check",
        default_transaction_read_only: "on",
        statement_timeout: 3000,
      },
    });
    const [row] = await sql`SELECT current_setting('data_directory', true) AS directory`;
    return await compareDirectory(row?.directory, dataDir);
  } catch (error) {
    if (error.code === "ERR_MODULE_NOT_FOUND") return "probe-unavailable";
    if (["28P01", "28000", "42501"].includes(error.code)) return "sql-auth-failed";
    if (error.code === "57P03") return "sql-not-ready";
    if (["CONNECT_TIMEOUT", "ETIMEDOUT", "57014"].includes(error.code)) return "sql-timeout";
    return "sql-unavailable";
  } finally {
    await sql?.end({ timeout: 1 });
  }
}

// Bound the whole probe, including an unresponsive peer and driver shutdown.
const deadline = setTimeout(() => {
  console.log("sql-timeout");
  process.exit(0);
}, 6500);
try {
  console.log(await inspect(Number(process.argv[2]), process.argv[3], process.argv[4]));
} catch {
  console.log("probe-unavailable");
} finally {
  clearTimeout(deadline);
}
