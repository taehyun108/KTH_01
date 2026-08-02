import { z } from "zod";

/** 도메인 값 T 의 Zod 스키마 (§2 산출물). verifiedFactSchema(valueSchema) 로 감싼다. */

export const GeoPointSchema = z.object({
  lat: z.number().min(-90).max(90),
  lng: z.number().min(-180).max(180),
});

export const CurrencyInfoSchema = z.object({
  code: z.string().length(3),
  krw_per_unit: z.number().positive(),
  base: z.literal("KRW"),
  card_practice: z.string().optional(),
  tipping_practice: z.string().optional(),
});

export const WeatherDaySchema = z.object({
  date: z.iso.date(),
  temp_min_c: z.number(),
  temp_max_c: z.number(),
  precipitation_probability: z.number().min(0).max(100).optional(),
  kind: z.enum(["forecast", "climatology"]),
});

const OpeningHoursSchema = z.array(z.string().nullable());

export const PoiSchema = z.object({
  name: z.string().min(1),
  location: GeoPointSchema,
  opening_hours: OpeningHoursSchema.optional(),
  closed_days: z.array(z.number().int().min(0).max(6)).optional(),
  admission_fee_local: z.number().nonnegative().nullable().optional(),
  reservation_required: z.boolean().optional(),
});

export const RestaurantSchema = z.object({
  name: z.string().min(1),
  location: GeoPointSchema,
  opening_hours: OpeningHoursSchema.optional(),
  closed_days: z.array(z.number().int().min(0).max(6)).optional(),
  price_level: z.union([z.literal(1), z.literal(2), z.literal(3), z.literal(4)]).optional(),
  reservation_required: z.boolean().optional(),
});

export const FlightOptionSchema = z.object({
  flight_no: z.string().min(2),
  depart_local: z.iso.datetime({ offset: true }),
  arrive_local: z.iso.datetime({ offset: true }),
  stops: z.number().int().min(0),
  duration_minutes: z.number().int().positive(),
  price_estimate_krw: z.number().nonnegative().optional(),
});

export const TravelLegSchema = z.object({
  from: GeoPointSchema,
  to: GeoPointSchema,
  mode: z.enum(["walk", "transit", "car"]),
  minutes: z.number().nonnegative(),
});

export const LogisticsInfoSchema = z.object({
  visa_required: z.boolean().optional(),
  entry_requirements: z.string().optional(),
  power_plug: z.string().optional(),
  esim_note: z.string().optional(),
  public_holidays: z.array(z.iso.date()).optional(),
});
