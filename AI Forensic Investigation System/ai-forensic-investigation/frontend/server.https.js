// HTTPS dev server for the physical-camera flow.
//
// The phone's browser requires a *secure context* to access getUserMedia, so
// the Live Camera page must be served over HTTPS when the phone is reached via
// a LAN IP (localhost is exempt, but the phone can't use the PC's localhost).
//
// Usage:
//   1. Generate a cert for the PC's LAN IP (see scripts/make_dev_cert.py):
//        python scripts/make_dev_cert.py --ip <PC_LAN_IP>
//   2. Run Next over HTTPS:
//        python scripts/make_dev_cert.py --ip <PC_LAN_IP>
//        HTTPS_CERT_FILE=scripts/cert.pem HTTPS_KEY_FILE=scripts/key.pem npm run dev:https
//   3. Open https://<PC_LAN_IP>:3000/live on the phone.
//
// A thin wrapper around Next's custom server API (the same API `next dev` /
// `next start` use) with cert files taken from the environment; no extra
// runtime dependency is required.

const { createServer } = require("https");
const { parse } = require("url");
const { readFileSync } = require("fs");
const path = require("path");
const fs = require("fs");

const certFile = process.env.HTTPS_CERT_FILE || path.join(process.cwd(), "scripts/cert.pem");
const keyFile = process.env.HTTPS_KEY_FILE || path.join(process.cwd(), "scripts/key.pem");

if (!fs.existsSync(certFile) || !fs.existsSync(keyFile)) {
  console.error(
    [
      `Missing HTTPS cert files.`,
      `  cert: ${certFile}`,
      `  key : ${keyFile}`,
      `Generate them first:`,
      `  python scripts/make_dev_cert.py --ip <your-PC-LAN-IP>`,
      ``,
      `Then run this script from frontend/ (or set HTTPS_CERT_FILE / HTTPS_KEY_FILE).`,
    ].join("\n")
  );
  process.exit(1);
}

const dir = __dirname;
const next = require("next");
const app = next({ dev: true, hostname: "0.0.0.0", port: 3000, dir });
const handle = app.getRequestHandler();

const httpsOptions = {
  cert: readFileSync(certFile),
  key: readFileSync(keyFile),
};

app
  .prepare()
  .then(() => {
    createServer(httpsOptions, (req, res) => {
      const parsedUrl = parse(req.url, true);
      handle(req, res, parsedUrl);
    }).listen(3000, "0.0.0.0", () => {
      console.log("HTTPS dev server listening on https://0.0.0.0:3000");
      console.log(`  cert: ${certFile}`);
    });
  })
  .catch((err) => {
    console.error(err);
    process.exit(1);
  });