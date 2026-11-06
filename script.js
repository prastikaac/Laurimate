/* =========================================================
   Laurimate — Instructions website scripts
   ========================================================= */
(function () {
  'use strict';

  /* ---------- Navbar: scroll state, mobile toggle, active link ---------- */
  var nav = document.getElementById('nav');
  var toggle = document.getElementById('navToggle');
  var links = document.getElementById('navLinks');

  function onScroll() {
    nav.classList.toggle('scrolled', window.scrollY > 20);
  }
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  toggle.addEventListener('click', function () {
    toggle.classList.toggle('open');
    links.classList.toggle('open');
  });
  links.querySelectorAll('a').forEach(function (a) {
    a.addEventListener('click', function () {
      toggle.classList.remove('open');
      links.classList.remove('open');
    });
  });

  var sections = document.querySelectorAll('section[id]');
  var navAnchors = links.querySelectorAll('a');
  var sectionObserver = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (entry.isIntersecting) {
        navAnchors.forEach(function (a) {
          a.classList.toggle('active', a.getAttribute('href') === '#' + entry.target.id);
        });
      }
    });
  }, { rootMargin: '-45% 0px -50% 0px' });
  sections.forEach(function (s) { sectionObserver.observe(s); });

  /* ---------- Reveal on scroll ---------- */
  var revealObserver = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
        revealObserver.unobserve(entry.target);
      }
    });
  }, { threshold: 0.12 });
  function observeReveals(root) {
    (root || document).querySelectorAll('.reveal:not(.visible)').forEach(function (el) {
      revealObserver.observe(el);
    });
  }

  /* ---------- Counter ---------- */
  document.querySelectorAll('[data-count]').forEach(function (el) {
    var target = parseInt(el.getAttribute('data-count'), 10);
    var start = null;
    function step(ts) {
      if (!start) start = ts;
      var p = Math.min((ts - start) / 1600, 1);
      el.textContent = Math.floor(target * (1 - Math.pow(1 - p, 3))).toLocaleString('en-US');
      if (p < 1) requestAnimationFrame(step);
    }
    setTimeout(function () { requestAnimationFrame(step); }, 400);
  });

  /* ---------- Hero speech bubble typing ---------- */
  var bubble = document.getElementById('heroBubble');
  var phrases = [
    'Hello! I am Laurimate 👋',
    'Hei! Miten voin auttaa?',
    'Ask me about the library 📚',
    'Need the Wi-Fi? Just ask!',
    'Where is your classroom? 🧭',
    'Kysy minulta mitä vain!'
  ];
  var pi = 0, ci = 0, deleting = false;
  function typeLoop() {
    var text = phrases[pi];
    if (!deleting) {
      ci++;
      bubble.textContent = text.slice(0, ci);
      if (ci === text.length) { deleting = true; return setTimeout(typeLoop, 2200); }
      return setTimeout(typeLoop, 55);
    }
    ci--;
    bubble.textContent = text.slice(0, ci);
    if (ci === 0) { deleting = false; pi = (pi + 1) % phrases.length; return setTimeout(typeLoop, 350); }
    setTimeout(typeLoop, 25);
  }
  setTimeout(typeLoop, 2500);

  /* ---------- Example conversation animation ---------- */
  var convo = document.getElementById('convo');
  var played = false;
  new IntersectionObserver(function (entries, obs) {
    if (entries[0].isIntersecting && !played) {
      played = true;
      obs.disconnect();
      convo.querySelectorAll('.msg').forEach(function (m, i) {
        setTimeout(function () { m.classList.add('show'); }, 300 + i * 900);
      });
    }
  }, { threshold: 0.4 }).observe(convo);

  /* ---------- Topics (from functions/data/campus.json sections) ---------- */
  var topics = [
    { i: '🏫', t: 'Campus basics & directions', c: 40, q: ['Where is Laurea Leppävaara campus located?', 'Which entrance should new students use?', 'How do I activate building access?', 'Is there a taxi drop-off zone?'] },
    { i: '📇', t: 'Contacts & Study Services', c: 40, q: ['What does Study Services help with?', 'How do I get a Kela meal subsidy certificate?', 'What paperwork do I need for graduation?'] },
    { i: '📝', t: 'Applying & admission', c: 50, q: ['How do I apply to Laurea?', 'Is there an entrance exam?', 'How do I accept my study place?', 'What should I bring to orientation?'] },
    { i: '💻', t: 'Accounts, IT, email & Wi-Fi', c: 60, q: ['Where is the IT support page?', 'My mailbox is full, what do I do?', 'Eduroam keeps disconnecting — help?', 'How do I set up MFA?'] },
    { i: '📅', t: 'Schedules, courses & credits', c: 70, q: ['How do I find my timetable?', 'How do waiting lists work?', 'Which courses are mandatory?'] },
    { i: '🧪', t: 'Exams & assessment', c: 50, q: ['What exam types are there at Laurea?', 'How are exams scheduled?', 'Which grade counts after a retake?', 'What is a Turnitin similarity score?'] },
    { i: '📚', t: 'Library & printing', c: 60, q: ['What are the library opening hours?', 'How many times can I renew a book?', 'How do I access journals and databases?', 'What is the maximum print size?'] },
    { i: '🎉', t: 'Student life & wellbeing', c: 70, q: ['What is the student union Laureamko?', 'Where are the campus restaurants?', 'Are there student clubs?', 'Is there support for learning difficulties?'] },
    { i: '🎓', t: 'Thesis, internship & graduation', c: 60, q: ['When should I start my thesis?', 'Is the internship mandatory?', 'When can I go on exchange?'] },
    { i: '🏢', t: 'Campus facilities', c: 50, q: ['How do I reserve a group room online?', 'Are there USB charging ports?', 'Are there baby changing facilities?'] },
    { i: '👩‍🏫', t: 'Teaching & learning culture', c: 100, q: ['What is the LbD approach?', 'Is lecture attendance tracked?', 'How can I find a study group?'] },
    { i: '🧮', t: 'Degree structure & policies', c: 50, q: ['How many ECTS is a bachelor’s degree?', 'How many credits is the thesis?', 'Can I skip prerequisites?'] },
    { i: '✈️', t: 'Exchange & mobility', c: 100, q: ['What exchange programmes are there?', 'What are the exchange requirements?', 'Who is my exchange advisor?'] },
    { i: '🛠️', t: 'IT & developer projects', c: 100, q: ['Which programming languages are taught at Laurea?', 'Can I get API access for projects?', 'What AI and ML tools can I use?'] },
    { i: '💚', t: 'Wellbeing, legal & crisis', c: 20, q: ['Where can I get mental health support?', 'Who do I contact in a crisis?'] },
    { i: '📣', t: 'Community, events & admin', c: 30, q: ['How do I advertise an event on campus?', 'Can visitors borrow library materials?', 'How do I get transcript copies?'] },
    { i: '🗺️', t: 'Study planning & HOPS', c: 80, q: ['How do I read my degree structure?', 'What must I do now and what can wait?', 'How do I plan if I need more time?'] },
    { i: '✅', t: 'Course enrolment rules', c: 70, q: ['What is the difference between a course and an implementation?', 'Can I join a course late?'] },
    { i: '📤', t: 'Assignments & feedback', c: 100, q: ['How do I decode a vague assignment?', 'Canvas marked me late, what now?', 'How do I include references properly?'] },
    { i: '🔍', t: 'Exams — in depth', c: 90, q: ['What is the difference between open-book and closed-book?', 'I closed the exam page accidentally — help!', 'Can I use a second monitor?'] },
    { i: '🤝', t: 'Project-based learning', c: 100, q: ['How does LbD work day-to-day?', 'What if the client disappears mid-project?', 'My project uses personal data — what about GDPR?'] },
    { i: '🔬', t: 'Thesis & research', c: 120, q: ['What is the best time to start my thesis?', 'How do I write a thesis proposal email?', 'How do I recruit participants ethically?'] },
    { i: '💼', t: 'Internship & RPL / AHOT', c: 80, q: ['Is the internship mandatory and how many credits?', 'Which documents do I need to complete it?'] },
    { i: '🌍', t: 'Studying in English as an immigrant', c: 60, q: ['Do teachers grade language or content?', 'How do I avoid missing citations?', 'How can I participate with limited confidence?'] }
  ];

  var grid = document.getElementById('topicGrid');
  var exTitle = document.getElementById('exampleTitle');
  var exList = document.getElementById('exampleList');

  function showExamples(idx) {
    var tp = topics[idx];
    exTitle.textContent = tp.i + ' Try asking about ' + tp.t.toLowerCase() + '…';
    exList.innerHTML = '';
    tp.q.forEach(function (q) {
      var li = document.createElement('li');
      li.textContent = q;
      exList.appendChild(li);
    });
    grid.querySelectorAll('.topic').forEach(function (b, i) { b.classList.toggle('active', i === idx); });
  }

  topics.forEach(function (tp, idx) {
    var b = document.createElement('button');
    b.className = 'topic reveal';
    b.type = 'button';
    b.innerHTML = '<span class="ti">' + tp.i + '</span><span class="tt">' + tp.t +
      '<span class="tc">' + tp.c + ' questions</span></span>';
    b.addEventListener('click', function () { showExamples(idx); });
    grid.appendChild(b);
  });
  showExamples(6); // Library by default

  /* ---------- Tabs ---------- */
  var tabBtns = document.querySelectorAll('.tab-btn');
  tabBtns.forEach(function (btn) {
    btn.addEventListener('click', function () {
      tabBtns.forEach(function (b) { b.classList.remove('active'); });
      document.querySelectorAll('.tab-panel').forEach(function (p) { p.classList.remove('active'); });
      btn.classList.add('active');
      document.getElementById('tab-' + btn.getAttribute('data-tab')).classList.add('active');
    });
  });

  /* ---------- Copy buttons ---------- */
  document.querySelectorAll('.copy').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var text = btn.parentElement.querySelector('pre').innerText;
      function done() {
        btn.textContent = 'Copied!';
        btn.classList.add('done');
        setTimeout(function () { btn.textContent = 'Copy'; btn.classList.remove('done'); }, 1600);
      }
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(done);
      } else {
        var ta = document.createElement('textarea');
        ta.value = text; document.body.appendChild(ta); ta.select();
        try { document.execCommand('copy'); done(); } catch (e) { /* ignore */ }
        document.body.removeChild(ta);
      }
    });
  });

  /* ---------- Footer year ---------- */
  document.getElementById('year').textContent = new Date().getFullYear();

  observeReveals();
})();

