// Stands in for Ollama in the end-to-end test (spec 006 AC-15): a real model is slow and
// non-deterministic, and CI doesn't have one. Quotes must appear in the note the test writes.
import { createServer } from "node:http";
import { argv } from "node:process";

const answer = {
  dimensions: {
    mood: { quote: "ok evening", score: 3 },
    stress: { quote: "stressful meeting", score: 4 },
    energy: { quote: "words that are not in the note", score: 1 },
  },
  tags: ["workday", "a_tag_nobody_offered"],
};

createServer((request, response) => {
  request.resume();
  request.on("end", () => {
    response.setHeader("Content-Type", "application/json");
    response.end(
      JSON.stringify({ message: { role: "assistant", content: JSON.stringify(answer) } }),
    );
  });
}).listen(Number(argv[2]), "127.0.0.1");
