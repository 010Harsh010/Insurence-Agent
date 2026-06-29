import http from "k6/http";
import { Counter } from "k6/metrics";


const success = new Counter("success_requests");
const limited = new Counter("rate_limited_requests");


export const options = {
  stages: [
    { duration: "10s", target: 20 },
    { duration: "20s", target: 20 },
    { duration: "10s", target: 0 },
  ],
};

const BASE_URL = "http://localhost:8000";

export default function () {
  const res =  http.get(`${BASE_URL}/health`);
  
  if( res.status === 200){
    success.add(1);
  }
  if( res.status === 429){
    limited.add(1); 
  }
}