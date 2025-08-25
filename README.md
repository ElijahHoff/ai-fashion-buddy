
# AI Fashion Buddy — One-Pager (GitHub-safe v2)

**Live demo:** <https://ai-fashion-buddy-vsaggwpwtyk4cksgocqdsp.streamlit.app/TryOn_Segmind_API>  
**Repo:** <https://github.com/ElijahHoff/ai-fashion-buddy>

---

## High-Level Architecture

```mermaid
flowchart TD
  U[User] -->|HTTP| S[Streamlit App]

  subgraph "App Services"
    A[Chat and Outfit Plan]
    B[Try-On SegFit v1.3]
    H[Palette Extractor]
  end

  A -.-> H
  H --> A

  A --> OAI[(OpenAI API)]
  B --> SegFit[(Segmind SegFit v1.3 API)]
  SegFit --> B

  A --> R[(Retailer Search Links)]
```

---

## Try-On Sequence (SegFit v1.3)

```mermaid
sequenceDiagram
  participant U as User
  participant UI as Streamlit UI
  participant PP as Preprocess
  participant API as SegFit v1.3 API

  U->>UI: Upload two images (model and outfit)
  UI->>PP: Normalize (RGB, resize)
  PP-->>UI: base64
  UI->>API: POST model_image and outfit_image with params
  API-->>UI: 200 (image b64) or 4xx/5xx

  alt success
    UI->>UI: Decode, optional upscale, render
  else error
    UI->>UI: Fallback strategy (Balanced, smaller size, no seed)
  end
```

---

## Roadmap (Areas)

```mermaid
flowchart LR
  subgraph "UX"
    UX1[Save looks and history] --> UX2[Personal wardrobe]
    UX2 --> UX3[Recommend using owned items]
    UX1 --> UX4[Share looks - link or QR]
  end

  subgraph "TryOn"
    T1[Compose multiple items] --> T2[Backgrounds and lighting]
    T1 --> T3[Hair or makeup adjust]
    T4[Local VTON fallback]
  end

  subgraph "Search"
    S1[Retailer APIs] --> S2[Stock and price filters]
    S3[Affiliate tags]
  end

  subgraph "Intelligence"
    I1[Size recommender] --> I2[Learning from clicks and orders]
    I3[A or B prompts]
  end

  subgraph "Ops"
    O1[Telemetry and logging] --> O2[Caching and quotas]
    O3[SLA monitoring]
  end
```

---

## Checklist
- [ ] Retailer APIs (size and stock filters)
- [ ] Size recommendations
- [ ] Save or share looks; try-on history
- [ ] Multi-item try-on (top, bottom, shoes)
- [ ] Local VTON backup path
- [ ] i18n (RU, EN, DE) and dark theme
- [ ] Metrics: retailer CTR, P95 to result, success rate
