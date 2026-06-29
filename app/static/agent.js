const systemCopy = {
  占星: {
    pill: "推荐：占星行运",
    title: "这类近期波动，先用占星行运看",
    reason: "如果你要看对方当下想法，我会建议切到塔罗；如果是具体事件结果，再切六爻。",
    label: "占星行运",
  },
  八字: {
    pill: "推荐：八字大运",
    title: "长期人生节奏，更适合用八字看结构",
    reason: "八字会优先看命局、十神、大运和流年，再给出阶段建议。",
    label: "八字命理",
  },
  塔罗: {
    pill: "推荐：塔罗牌阵",
    title: "想看对方想法，可以切到塔罗",
    reason: "塔罗适合回答当下状态、关系互动和短期选择，不替代长期命盘判断。",
    label: "塔罗牌阵",
  },
  六爻: {
    pill: "推荐：六爻断事",
    title: "具体事情能不能成，优先用六爻",
    reason: "六爻更适合有明确问题和时间点的判断，比如合作、结果、等待与取舍。",
    label: "六爻断事",
  },
  合盘: {
    pill: "推荐：关系合盘",
    title: "长期关系模式，可以用合盘拆解",
    reason: "合盘会看双方吸引、冲突、承诺感和相处节奏，适合稳定关系分析。",
    label: "关系合盘",
  },
  签文: {
    pill: "推荐：灵感签文",
    title: "想要一句提醒，可以用签文收束问题",
    reason: "签文适合快速获得方向感，我会把它翻译成可执行的行动建议。",
    label: "签文指引",
  },
};

const actionToSystem = {
  astrology: "占星",
  tarot: "塔罗",
  liuyao: "六爻",
};

const chatStream = document.querySelector("#chatStream");
const input = document.querySelector("#agentInput");
const composer = document.querySelector("#composer");
const routePill = document.querySelector("#routePill");
const routeTitle = document.querySelector("#routeTitle");
const routeReason = document.querySelector("#routeReason");
const memoryToggle = document.querySelector("#memoryToggle");
let activeSystem = "占星";

function setSystem(system) {
  activeSystem = system;
  const copy = systemCopy[system];
  document.querySelectorAll(".system-chip").forEach((button) => {
    button.classList.toggle("active", button.dataset.system === system);
  });
  document.querySelectorAll(".tool-card").forEach((button) => {
    button.classList.toggle("active", button.dataset.tool === system);
  });
  routePill.textContent = copy.pill;
  routeTitle.textContent = copy.title;
  routeReason.textContent = copy.reason;
}

function appendMessage(role, label, text) {
  const article = document.createElement("article");
  article.className = `message ${role === "user" ? "user-message" : "agent-message"}`;
  const name = document.createElement("span");
  name.textContent = label;
  const body = document.createElement("p");
  body.textContent = text;
  article.append(name, body);
  chatStream.append(article);
  article.scrollIntoView({ behavior: "smooth", block: "end" });
  return body;
}

function buildReply(question) {
  const copy = systemCopy[activeSystem];
  if (!question.trim()) {
    return "你可以直接描述问题，我会先判断该用哪一种占术，再把答案压缩成结论、原因和行动建议。";
  }
  return `我会用${copy.label}来处理这个问题。先看重点：这不是简单好坏判断，而是要分清当前变量、你的真实诉求和接下来最小的一步。建议你先稳住节奏，别急着一次性把关系、事业或结果全部定死。`;
}

function streamAgentReply(question) {
  const copy = systemCopy[activeSystem];
  const body = appendMessage("agent", `Nexa Agent · ${copy.label}`, "");
  const reply = buildReply(question);
  let index = 0;
  const timer = window.setInterval(() => {
    body.textContent = reply.slice(0, index);
    index += 2;
    if (index > reply.length + 2) {
      body.textContent = reply;
      window.clearInterval(timer);
    }
  }, 18);
}

document.querySelectorAll(".system-chip").forEach((button) => {
  button.addEventListener("click", () => setSystem(button.dataset.system));
});

document.querySelectorAll("[data-action]").forEach((button) => {
  button.addEventListener("click", () => {
    setSystem(actionToSystem[button.dataset.action]);
    streamAgentReply("");
  });
});

document.querySelectorAll(".tool-card").forEach((button) => {
  button.addEventListener("click", () => {
    setSystem(button.dataset.tool);
    input.value = button.dataset.tool === "塔罗" ? "帮我看看对方现在怎么想" : "";
    input.focus();
  });
});

document.querySelectorAll("[data-question]").forEach((button) => {
  button.addEventListener("click", () => {
    input.value = button.dataset.question;
    input.focus();
  });
});

memoryToggle.addEventListener("click", () => {
  memoryToggle.classList.toggle("active");
});

composer.addEventListener("submit", (event) => {
  event.preventDefault();
  const question = input.value.trim();
  if (!question) {
    input.focus();
    return;
  }
  appendMessage("user", "你", question);
  input.value = "";
  window.setTimeout(() => streamAgentReply(question), 180);
});
