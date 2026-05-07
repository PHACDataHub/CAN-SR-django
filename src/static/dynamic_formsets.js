// this approach is documented here https://www.brennantymrak.com/articles/django-dynamic-formsets-javascript
// changed a few things, like using an empty-form template
class DynamicFormsetManager {
    constructor({ formsetPrefix, formListSelector, templateContainerSelector, addButtonSelector }) {
        this.formsetPrefix = formsetPrefix;
        // this.formClass = formClass;
        this.formListSelector = formListSelector;
        this.templateContainerSelector = templateContainerSelector;
        this.addButtonSelector = addButtonSelector;


        // trigger validation checks
        this.getAddButton();
        this.getTemplateContainer();

    }

    activate() {
        //only public method
        this.getAddButton().addEventListener('click', this.addForm.bind(this));
    }

    // "private" methods:
    getTemplateContainer() {
        const node = document.querySelector(this.templateContainerSelector);
        if (!node) {
            throw new Error(`No element found with selector ${this.templateContainerSelector} (templateContainerSelector)`);
        }
        if (node.children.length !== 1) {
            throw new Error(`The templateContainer should contain a single child node, which is the template`);
        }
        return node;
    }
    getFormTemplateNode() {
        return this.getTemplateContainer().children[0];
    }

    getAddButton() {
        const node = document.querySelector(this.addButtonSelector)
        if (!node) {
            throw new Error(`No element found with selector ${this.addButtonSelector} (addButtonSelector)`);
        }
        return node;
    }

    setTotalFormsCount(numForms) {
        return document.querySelector(`#id_${this.formsetPrefix}-TOTAL_FORMS`).setAttribute('value', `${numForms}`);
    }

    getFormNodes() {
        //override in case your have extra nodes that don't correspond to forms

        // these aren't <forms>, but rather the container that is duplicated for each form and contains a single form's inputs
        // return Array.from(document.querySelectorAll(`.${this.formClass}`)).filter(node => node !== this.getFormTemplateNode());
        return Array.from(this.getFormListContainer().children);
    }

    getFormListContainer() {
        // return this.getFormNodes()[0].parentNode;
        const node = document.querySelector(this.formListSelector);
        if (!node) {
            throw new Error(`No element found with selector ${this.formListSelector} (formListSelector)`);
        }
        return node;
    }

    getAriaLabelsSection() {
        const node = document.querySelector(`#${this.formsetPrefix}-aria-labels-container`);
        return node;
    }

    getNewHtmlForForm(newFormIndex) {
        const { formsetPrefix } = this;
        const formTemplateNode = this.getFormTemplateNode();
        const fieldFormRegex = RegExp(`${formsetPrefix}-__prefix__-`, 'g')
        const fragmentsFormRegex = RegExp(`fragment-${formsetPrefix}-__prefix__`, 'g')

        const newFormHtml = formTemplateNode.outerHTML
            .replace(fieldFormRegex, `${formsetPrefix}-${newFormIndex}-`)
            // note the fragment IDs don't have a '-' suffix
            .replace(fragmentsFormRegex, `fragment-${formsetPrefix}-${newFormIndex}`)
            .replaceAll(
                // in case the index needs to be used in text, e.g. aria labels
                "REPLACE_ME_WITH_INDEX",
                newFormIndex
            );


        return newFormHtml
    }

    createNewFormNode(formIndex) {
        // override in case, e.g. index needs to be used in text


        // It would be easier to write the parent's innerHTML
        // but that would risk losing event listeners, potentially the addButton! 
        // Also, since we don't know what nodeType the form is
        // we use a dummy parent rather than createElement(unknownNodeType)
        const dummyContainer = document.createElement('div')
        dummyContainer.innerHTML = this.getNewHtmlForForm(formIndex)
        const newForm = dummyContainer.children[0]

        return newForm;
    }

    addIndexAriaLabel(formIndex) {
        const ariaLabelsSection = this.getAriaLabelsSection();

        if (!ariaLabelsSection) {
            // not all formsets support aria-labels
            return;
        }

        const ariaIndexLabelTemplate = ariaLabelsSection.querySelector('.form-index-label-template');

        if (!ariaIndexLabelTemplate) {
            throw new Error(`No element found with class 'form-index-label-template' in aria labels section. This template is required to add aria labels for new forms.`)
        }

        const newAriaIndexLabel = ariaIndexLabelTemplate.cloneNode(true);
        newAriaIndexLabel.classList.remove('form-index-label-template')
        newAriaIndexLabel.querySelector('.entry-index').textContent = formIndex + 1;
        const newId = newAriaIndexLabel.getAttribute('id').replace("REPLACE_ME_WITH_INDEX", formIndex)
        newAriaIndexLabel.setAttribute('id', newId)


        ariaLabelsSection.appendChild(newAriaIndexLabel);
    }


    addForm(e) {
        e.preventDefault();

        const previousNumForms = this.getFormNodes().length
        const newFormIndex = previousNumForms; // indexing starts at 0
        const newNumForms = previousNumForms + 1; //total forms after addition
        const formListContainer = this.getFormListContainer()

        const newFormNode = this.createNewFormNode(newFormIndex);

        formListContainer.appendChild(newFormNode);

        this.addIndexAriaLabel(newFormIndex);

        this.setTotalFormsCount(newNumForms);
        htmx.process(newFormNode);
    }


}

