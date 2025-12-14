# Persona: The Local Journalist

## Profile
**Name:** Maria Santos  
**Age:** 45  
**Occupation:** Reporter for regional newspaper covering 5 suburban communities  
**Tech Comfort:** Medium-high — uses research tools, databases, but not a coder  
**Time Available:** Very limited — covers too many communities for too few reporters

## Backstory
Maria covers Twinsburg plus 4 other cities for a regional paper. She can't attend every meeting, can't read every document, and relies heavily on tips and press releases. She misses stories because she doesn't have time to monitor everything. She's been a journalist for 20 years and has seen local news coverage shrink dramatically.

## Primary Use Cases

### 1. "What did I miss?"
- Quick scan of all meetings across her coverage area
- Highlights: What's controversial? What's new?
- Compare: Did multiple cities discuss the same topic?

### 2. "Deep dive on a story"
- Full-text search for names, topics, addresses
- Timeline of how an issue evolved
- Find original documents and quotes

### 3. "Background for interviews"
- Before interviewing a council member: What have they voted on?
- What has the city said about this issue before?
- Find contradictions between past and present statements

### 4. "Verify a tip"
- Resident says: "The city approved a variance for that property"
- Need to find the specific meeting and decision
- Verify claims quickly without FOIA requests

## Pain Points with Current System
- "I cover 5 cities, each with different websites, different formats"
- "I miss important votes because I can't be everywhere"
- "By the time I file a records request, the story is stale"
- "I spend more time finding documents than writing stories"

## What Would Delight Maria
- Multi-city aggregation (federated vision)
- Alerts for keywords: "Whenever 'development agreement' is mentioned"
- Quick access to quotes and vote records
- Reduce FOIA dependence for public meeting records

## Feedback on Current Design

### 👍 Likes
- Full-text search across documents — exactly what she needs
- PDF extraction to searchable text — game changer
- MCP for natural language queries — can ask questions not just search
- Federation vision — covering multiple cities is the dream

### 👎 Concerns
- Single-city deployment in v1 — she needs multi-city now
- No mention of keyword alerts/notifications
- Are meeting minutes complete or summarized? She needs quotes
- Can she trust AI summaries for accuracy? (Journalistic standards)

### 💡 Suggestions
- Add keyword alert subscriptions (email when "rezoning" appears)
- Preserve exact quotes, not just summaries
- Add entity extraction: Names, addresses, dollar amounts
- Vote tracking: How did each member vote?
- Export features for creating story timelines
- Accuracy confidence scores on AI summaries
- Link to original source documents for verification

## Key Questions for This Persona
1. Is the full original text preserved, or just summaries?
2. Can she set up alerts for specific keywords or topics?
3. How accurate are AI summaries? Can she quote them?
4. When is multi-city (federated) support coming?
5. Can this reduce her public records request burden?
