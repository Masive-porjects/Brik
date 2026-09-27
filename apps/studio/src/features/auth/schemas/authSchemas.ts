import { z } from "zod";

type TranslateFn = (key: string, fallback?: string) => string;

export const createEmailSchema = (t?: TranslateFn) =>
  z
    .string()
    .min(
      1,
      t ? t("auth.valEmailRequired", "El correo electrónico es requerido") : "El correo electrónico es requerido"
    )
    .email(
      t ? t("auth.valEmailInvalid", "Ingresa un correo electrónico válido") : "Ingresa un correo electrónico válido"
    )
    .regex(
      /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/,
      t
        ? t(
            "auth.valEmailDomain",
            "Ingresa un correo con dominio válido (ej: usuario@dominio.com)"
          )
        : "Ingresa un correo con dominio válido (ej: usuario@dominio.com)"
    );

export const createStrongPasswordSchema = (t?: TranslateFn) =>
  z
    .string()
    .min(
      8,
      t
        ? t("auth.valPasswordMin8", "La contraseña debe tener al menos 8 caracteres")
        : "La contraseña debe tener al menos 8 caracteres"
    )
    .regex(
      /[A-Z]/,
      t
        ? t("auth.valPasswordUpper", "Debe contener al menos una letra mayúscula (A-Z)")
        : "Debe contener al menos una letra mayúscula (A-Z)"
    )
    .regex(
      /[a-z]/,
      t
        ? t("auth.valPasswordLower", "Debe contener al menos una letra minúscula (a-z)")
        : "Debe contener al menos una letra minúscula (a-z)"
    )
    .regex(
      /[0-9]/,
      t
        ? t("auth.valPasswordNumber", "Debe contener al menos un número (0-9)")
        : "Debe contener al menos un número (0-9)"
    )
    .regex(
      /[^A-Za-z0-9]/,
      t
        ? t(
            "auth.valPasswordSpecial",
            "Debe contener al menos un carácter especial (@, #, $, %, etc.)"
          )
        : "Debe contener al menos un carácter especial (@, #, $, %, etc.)"
    );

export const createLoginPasswordSchema = (t?: TranslateFn) =>
  z
    .string()
    .min(
      1,
      t ? t("auth.valPasswordRequired", "La contraseña es requerida") : "La contraseña es requerida"
    )
    .min(
      6,
      t
        ? t("auth.valPasswordMin6", "La contraseña debe tener al menos 6 caracteres")
        : "La contraseña debe tener al menos 6 caracteres"
    );

export const getLoginSchema = (t?: TranslateFn) =>
  z.object({
    email: createEmailSchema(t),
    password: createLoginPasswordSchema(t),
  });

export const getRegisterSchema = (t?: TranslateFn) =>
  z.object({
    fullName: z
      .string()
      .min(
        2,
        t
          ? t("auth.valNameMin2", "El nombre debe tener al menos 2 caracteres")
          : "El nombre debe tener al menos 2 caracteres"
      )
      .max(
        50,
        t
          ? t("auth.valNameMax50", "El nombre no puede exceder 50 caracteres")
          : "El nombre no puede exceder 50 caracteres"
      ),
    email: createEmailSchema(t),
    password: createStrongPasswordSchema(t),
  });

// Static default instances for type inference and default usage
export const loginSchema = getLoginSchema();
export const registerSchema = getRegisterSchema();

export type LoginFormData = z.infer<typeof loginSchema>;
export type RegisterFormData = z.infer<typeof registerSchema>;
