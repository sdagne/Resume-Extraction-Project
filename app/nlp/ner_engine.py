import spacy
from app.utils.logger import get_logger

logger = get_logger(__name__)

class NEREngine:
    def __init__(self, model_name: str = "en_core_web_md"):
        try:
            self.nlp = spacy.load(model_name)
        except OSError:
            logger.warning(f"Spacy model {model_name} not found. Loading base 'en_core_web_sm'.")
            try:
                self.nlp = spacy.load("en_core_web_sm")
            except OSError:
                logger.error("No Spacy models found. NER will fail.")
                self.nlp = None

    def extract_entities(self, text: str):
        """Extract PERSON, ORG, GPE, and DATE entities."""
        doc = self.nlp(text)
        entities = {
            "PERSON": [],
            "ORG": [],
            "GPE": [],
            "DATE": []
        }
        
        for ent in doc.ents:
            if ent.label_ in entities:
                entities[ent.label_].append(ent.text)
                
        # Deduplicate
        for key in entities:
            entities[key] = list(set(entities[key]))
            
        return entities

ner_engine = NEREngine()
