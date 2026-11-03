import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@supabase/supabase-js";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    if (!id) {
      return NextResponse.json({ error: "Missing track ID" }, { status: 400 });
    }

    const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!;
    const supabaseKey = process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;
    const supabase = createClient(supabaseUrl, supabaseKey);

    const { data: track, error } = await supabase
      .from("tracks")
      .select("display_name, master_url, name")
      .eq("id", id)
      .single();

    if (error || !track || !track.master_url) {
      return NextResponse.json({ error: "Track or master audio not found" }, { status: 404 });
    }

    const audioResponse = await fetch(track.master_url);
    if (!audioResponse.ok) {
      return NextResponse.json({ error: "Failed to fetch audio from storage" }, { status: 500 });
    }

    const rawName = track.display_name || track.name || "mastered_track";
    const cleanFileName = rawName.replace(/[^a-zA-Z0-9_\-]/g, "_");

    const audioBlob = await audioResponse.blob();
    const headers = new Headers();
    headers.set("Content-Type", "audio/wav");
    headers.set("Content-Disposition", `attachment; filename="${cleanFileName}_mastered.wav"`);

    return new NextResponse(audioBlob, {
      status: 200,
      headers,
    });
  } catch (err) {
    console.error("Download route error:", err);
    return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
  }
}