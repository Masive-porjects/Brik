import {
  IntentParseError,
  NEUTRAL_PROFILE,
  interpretIntent,
  type ChatTurn,
  type IntentProfile,
  type TrackAnalysis,
} from "@midimastering/agent";

/**
 * Puente entre el chat y el agente de interpretacion.
 * interpretIntent es una funcion pura sobre (historial, perfil, analisis).
 */

interface ChatRequest {
  messages: ChatTurn[];
  profile?: IntentProfile;
  voiceMode?: boolean;
  /** Analisis de AudioMind. Con esto el agente calibra cuanto mover cada eje. */
  analysis?: TrackAnalysis;
}

export async function POST(request: Request): Promise<Response> {
  let body: ChatRequest;
  try {
    body = (await request.json()) as ChatRequest;
  } catch {
    return Response.json({ error: "Body invalido" }, { status: 400 });
  }

  if (!Array.isArray(body.messages) || body.messages.length === 0) {
    return Response.json({ error: "Falta messages" }, { status: 400 });
  }

  // Validar aca da un mensaje util en vez de un 500 opaco cuando falta la key.
  if (!process.env.GEMINI_API_KEY) {
    return Response.json(
      { error: "Falta GEMINI_API_KEY. Copiá apps/studio/.env.example a .env.local y completala." },
      { status: 503 },
    );
  }

  try {
    const result = await interpretIntent({
      messages: body.messages,
      currentProfile: body.profile ?? NEUTRAL_PROFILE,
      analysis: body.analysis,
      voiceMode: body.voiceMode ?? false,
    });
    return Response.json(result);
  } catch (error) {
    if (error instanceof IntentParseError) {
      return Response.json({ error: error.message }, { status: 502 });
    }
    throw error;
  }
}
