The code below contains a design. This design should be used to create a new app or be added to an existing one.

Look at the current open project to determine if a project exists. If no project is open, create a new Vite project then create this view in React after componentizing it.

If a project does exist, determine the framework being used and implement the design within that framework. Identify whether reusable components already exist that can be used to implement the design faithfully and if so use them, otherwise create new components. If other views already exist in the project, make sure to place the view in a sensible route and connect it to the other views.

Ensure the visual characteristics, layout, and interactions in the design are preserved with perfect fidelity.

Run the dev command so the user can see the app once finished.

```
<html lang="en" vid="0"><head vid="1">
<meta charset="UTF-8" vid="2">
<meta name="viewport" content="width=device-width, initial-scale=1.0" vid="3">
<title vid="4">Architecture Models | MilkStraw AI</title>
<link rel="preconnect" href="https://fonts.googleapis.com" vid="5">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin="" vid="6">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500&amp;family=JetBrains+Mono:wght@400;500&amp;display=swap" rel="stylesheet" vid="7">
<style vid="8">
  :root {
    --black: #000000;
    --white: #F3F3F3;
    --grey-dark: #1A1A1A; 
    --grey-mid: #4A4A4A;  
    --grey-light: #8A8A8A; 
    --cyan: #5CB8E4;
    
    --font-sans: 'Inter', -apple-system, sans-serif;
    --font-mono: 'JetBrains Mono', monospace;
  }

  * {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
  }

  body {
    background-color: var(--black);
    color: var(--white);
    font-family: var(--font-sans);
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    overflow-x: hidden;
  }

  .text-huge {
    font-family: var(--font-sans);
    font-size: clamp(3rem, 6vw, 6rem);
    letter-spacing: -0.04em;
    line-height: 0.9;
    font-weight: 400;
  }

  .text-mono-sm {
    font-family: var(--font-mono);
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--grey-light);
  }

  .text-mono-xs {
    font-family: var(--font-mono);
    font-size: 9px;
    letter-spacing: 0.12em;
    color: var(--grey-mid);
    text-transform: uppercase;
  }

  .border-b { border-bottom: 1px solid var(--grey-dark); }
  .border-r { border-right: 1px solid var(--grey-dark); }

  .top-nav {
    display: flex;
    justify-content: space-between;
    padding: 1.5rem 2rem;
    align-items: center;
    position: sticky;
    top: 0;
    z-index: 100;
    background: var(--black);
  }

  .nav-link {
    text-decoration: none;
    color: var(--grey-light);
    transition: color 0.2s;
  }
  .nav-link:hover { color: var(--white); }

  
  .page-header {
    padding: 4rem 2rem;
    display: grid;
    grid-template-columns: 1fr 1fr;
    align-items: flex-end;
  }

  .models-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    border-top: 1px solid var(--grey-dark);
  }

  .model-card {
    padding: 3rem 2rem;
    min-height: 500px;
    display: flex;
    flex-direction: column;
    transition: background 0.3s ease;
  }
  
  .model-card:hover {
    background: #050505;
  }

  .model-ascii-container {
    height: 180px;
    display: flex;
    align-items: center;
    justify-content: center;
    margin-bottom: 2rem;
    background: rgba(255,255,255,0.02);
    border: 1px solid var(--grey-dark);
    font-family: var(--font-mono);
    font-size: 12px;
    line-height: 1.1;
    color: var(--grey-mid);
  }

  .model-title {
    font-size: 1.75rem;
    font-weight: 300;
    margin-bottom: 1rem;
    letter-spacing: -0.02em;
  }

  .model-desc {
    font-size: 0.95rem;
    color: var(--grey-light);
    line-height: 1.6;
    margin-bottom: 2rem;
    font-weight: 300;
  }

  .spec-row {
    display: flex;
    justify-content: space-between;
    padding: 0.75rem 0;
    border-top: 1px solid var(--grey-dark);
  }

  .c-cyan { color: var(--cyan); }
  
  .tag {
    font-family: var(--font-mono);
    font-size: 9px;
    padding: 2px 6px;
    border: 1px solid var(--cyan);
    color: var(--cyan);
    display: inline-block;
    margin-bottom: 1rem;
  }

  .footer-meta {
    padding: 4rem 2rem;
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 2rem;
  }

  @media (max-width: 1024px) {
    .models-grid { grid-template-columns: 1fr 1fr; }
    .page-header { grid-template-columns: 1fr; gap: 2rem; }
  }

  @media (max-width: 768px) {
    .models-grid { grid-template-columns: 1fr; }
    .footer-meta { grid-template-columns: 1fr 1fr; }
  }
</style>
</head>
<body vid="9">

  <nav class="top-nav border-b" vid="10">
    <a href="/" class="text-mono-sm nav-link" vid="11">[ BACK TO INDEX ]</a>
    <div class="text-mono-sm" vid="12">DIRECTORY: ARCHITECTURE_MODELS_V4.02</div>
  </nav>

  <header class="page-header border-b" vid="13">
    <div vid="14">
      <div class="text-mono-xs" style="margin-bottom: 1rem;" vid="15">INFRASTRUCTURE TOPOLOGY</div>
      <h1 class="text-huge" vid="16">Structural<br vid="17">Efficiency.</h1>
    </div>
    <div vid="18">
      <p class="text-mono-sm" style="max-width: 400px; line-height: 1.6; color: var(--white);" vid="19">
        MilkStraw AI deploys three core architecture models designed for liquidity, resilience, and maximum capital capture across cloud geographies.
      </p>
    </div>
  </header>

  <main class="models-grid" vid="20">
    
    <div class="model-card border-r border-b" vid="21">
      <div class="tag" vid="22">MOST LIQUID</div>
      <div class="model-ascii-container" vid="23">
<pre vid="24">   <span class="c-cyan" vid="25">/ \</span>
  <span class="c-cyan" vid="26">/---\</span>
 <span class="c-cyan" vid="27">/     \</span>
<span class="c-cyan" vid="28">|   |   |</span>
<span class="c-cyan" vid="29">|  -+-  |</span>
<span class="c-cyan" vid="30">|   |   |</span>
 <span class="c-cyan" vid="31">\     /</span>
  <span class="c-cyan" vid="32">\---/</span>
</pre>
      </div>
      <h2 class="model-title" vid="33">Fluid Instance</h2>
      <p class="model-desc" vid="34">Instant-settlement compute nodes with zero-duration commitments. Ideal for high-volatility batch processing and unpredictable horizontal scaling.</p>
      
      <div class="spec-row" vid="35">
        <span class="text-mono-xs" vid="36">Commitment</span>
        <span class="text-mono-xs c-cyan" vid="37">NONE / SPOT-EQUIV</span>
      </div>
      <div class="spec-row" vid="38">
        <span class="text-mono-xs" vid="39">Reliability</span>
        <span class="text-mono-xs" vid="40">99.9% (SLA)</span>
      </div>
      <div class="spec-row" vid="41">
        <span class="text-mono-xs" vid="42">Latency</span>
        <span class="text-mono-xs" vid="43">&lt; 15MS</span>
      </div>
    </div>

    
    <div class="model-card border-r border-b" vid="44">
      <div class="tag" style="border-color: var(--white); color: var(--white);" vid="45">OPTIMIZED</div>
      <div class="model-ascii-container" vid="46">
<pre vid="47">  <span class="c-cyan" vid="48">+-------+</span>
 /       /|
<span class="c-cyan" vid="49">+-------+</span> |
|       | <span class="c-cyan" vid="50">+</span>
|   <span class="c-cyan" vid="51">*</span>   |/
<span class="c-cyan" vid="52">+-------+</span>
</pre>
      </div>
      <h2 class="model-title" vid="53">Synthetic RI</h2>
      <p class="model-desc" vid="54">Leverages deep marketplace secondary liquidity to provide 3-year reservation pricing with monthly exit windows. Engineered for stable production workloads.</p>
      
      <div class="spec-row" vid="55">
        <span class="text-mono-xs" vid="56">Commitment</span>
        <span class="text-mono-xs c-cyan" vid="57">30-DAY WINDOW</span>
      </div>
      <div class="spec-row" vid="58">
        <span class="text-mono-xs" vid="59">Reliability</span>
        <span class="text-mono-xs" vid="60">99.99% (SLA)</span>
      </div>
      <div class="spec-row" vid="61">
        <span class="text-mono-xs" vid="62">Savings</span>
        <span class="text-mono-xs" vid="63">64-72% VS ON-DEMAND</span>
      </div>
    </div>

    
    <div class="model-card border-b" vid="64">
      <div class="tag" style="border-color: var(--grey-mid); color: var(--grey-mid);" vid="65">GLOBAL MESH</div>
      <div class="model-ascii-container" vid="66">
<pre vid="67"> <span class="c-cyan" vid="68">.---.   .---.</span>
<span class="c-cyan" vid="69">(     ) (     )</span>
 <span class="c-cyan" vid="70">`---'\ /`---'</span>
      <span class="c-cyan" vid="71">X</span>
 <span class="c-cyan" vid="72">.---./ \.---.</span>
<span class="c-cyan" vid="73">(     ) (     )</span>
 <span class="c-cyan" vid="74">`---'   `---'</span>
</pre>
      </div>
      <h2 class="model-title" vid="75">Geo-Cluster</h2>
      <p class="model-desc" vid="76">Distributed multi-region mesh for low-latency global delivery. Programmatic arbitrage shifts workloads across timezones for peak efficiency.</p>
      
      <div class="spec-row" vid="77">
        <span class="text-mono-xs" vid="78">Commitment</span>
        <span class="text-mono-xs c-cyan" vid="79">DYNAMIC</span>
      </div>
      <div class="spec-row" vid="80">
        <span class="text-mono-xs" vid="81">Availability</span>
        <span class="text-mono-xs" vid="82">MULTI-AZ NATIVE</span>
      </div>
      <div class="spec-row" vid="83">
        <span class="text-mono-xs" vid="84">Efficiency</span>
        <span class="text-mono-xs" vid="85">98.2% ADAPTIVE</span>
      </div>
    </div>
  </main>

  <footer class="footer-meta" vid="86">
    <div vid="87">
      <div class="text-mono-xs" vid="88">NODE_ALPHA</div>
      <div class="text-mono-sm" style="color: var(--white); margin-top: 0.5rem;" vid="89">US-EAST (VIRGINIA)<br vid="90">ACTIVE STATUS</div>
    </div>
    <div vid="91">
      <div class="text-mono-xs" vid="92">NODE_BRAVO</div>
      <div class="text-mono-sm" style="color: var(--white); margin-top: 0.5rem;" vid="93">EU-CENTRAL (FRA)<br vid="94">ACTIVE STATUS</div>
    </div>
    <div vid="95">
      <div class="text-mono-xs" vid="96">NODE_CHARLIE</div>
      <div class="text-mono-sm" style="color: var(--white); margin-top: 0.5rem;" vid="97">AP-SOUTHEAST (SIN)<br vid="98">PROVISIONING...</div>
    </div>
    <div vid="99">
      <div class="text-mono-xs" vid="100">SYSTEM HEALTH</div>
      <div class="text-mono-sm" style="color: var(--cyan); margin-top: 0.5rem;" vid="101">OPTIMIZED [100%]</div>
    </div>
  </footer>

</body></html>
```
