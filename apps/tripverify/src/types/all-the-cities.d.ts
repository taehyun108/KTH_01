declare module "all-the-cities" {
  interface City {
    cityId: number;
    name: string;
    altName?: string;
    country: string; // ISO2
    featureCode: string;
    adminCode: string;
    population: number;
    loc: { type: "Point"; coordinates: [number, number] }; // [lng, lat]
  }
  const cities: City[];
  export default cities;
}
