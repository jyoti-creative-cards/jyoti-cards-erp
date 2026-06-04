import { NextRequest, NextResponse } from "next/server";

const BACKEND =
  (process.env.BACKEND_URL || process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8002")
    .replace(/\/$/, "");

async function handler(req: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const targetUrl = `${BACKEND}/api/${path.join("/")}${req.nextUrl.search}`;

  const headers = new Headers();
  req.headers.forEach((value, key) => {
    if (!["host", "connection", "transfer-encoding"].includes(key.toLowerCase())) {
      headers.set(key, value);
    }
  });

  const body = ["GET", "HEAD"].includes(req.method) ? undefined : await req.arrayBuffer();

  try {
    const resp = await fetch(targetUrl, {
      method: req.method,
      headers,
      body: body && body.byteLength > 0 ? body : undefined,
      // @ts-expect-error Node fetch option
      duplex: "half",
    });

    const respHeaders = new Headers();
    resp.headers.forEach((value, key) => {
      if (!["transfer-encoding", "connection"].includes(key.toLowerCase())) {
        respHeaders.set(key, value);
      }
    });

    return new NextResponse(resp.body, {
      status: resp.status,
      headers: respHeaders,
    });
  } catch (err) {
    return NextResponse.json(
      { detail: `Cannot reach backend at ${BACKEND}. ${String(err)}` },
      { status: 503 }
    );
  }
}

export const GET = handler;
export const POST = handler;
export const PUT = handler;
export const PATCH = handler;
export const DELETE = handler;
export const OPTIONS = handler;
